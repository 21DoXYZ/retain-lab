"""Tegsoft call-provider adapter (звонилка — ТОЛЬКО через бэкенд).

Абстракция `CallProvider` + две реализации:
  - `TegsoftProvider`  — реальная телефония Tegsoft (login/originate/recordings).
                         ПИСАНО ПО ДОКАМ, НЕ ПРОВЕРЕНО ВЖИВУЮ (доступов к инстансу
                         клиента ещё нет — см. tegsoft/TEGSOFT_API_NOTES.md, п. «Открытые
                         вопросы»). Каждый непроверенный участок помечен `UNVERIFIED`.
  - `MockProvider`     — полный цикл без внешних вызовов (разработка/тесты/CI).

Секреты (usercode/password/token) живут только здесь, на сервере, и приходят из env.
Никогда не отдаём их наружу и не логируем.

Переключение mock↔tegsoft — ТОЛЬКО через env `CALL_PROVIDER`, без правок кода
(требование DoD раздела 6 SPA_BUILD_PLAN.md).
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from abc import ABC, abstractmethod
from typing import Iterator
from urllib.parse import urlencode

logger = logging.getLogger("tegsoft.adapter")

# ── дефолты/константы ─────────────────────────────────────────────────────────
_DEFAULT_TIMEOUT = float(os.environ.get("TEGSOFT_TIMEOUT", "15"))
_DEFAULT_RETRIES = int(os.environ.get("TEGSOFT_RETRIES", "2"))
_RETRY_BACKOFF = float(os.environ.get("TEGSOFT_RETRY_BACKOFF", "0.5"))


# ── ошибки ────────────────────────────────────────────────────────────────────
class CallProviderError(RuntimeError):
    """Базовая ошибка провайдера звонков (безопасна для показа наверх без секретов)."""


class TegsoftError(CallProviderError):
    """Транспортная/протокольная ошибка при обращении к Tegsoft."""


class TegsoftAuthError(TegsoftError):
    """Не удалось авторизоваться / сессия мертва и не восстановилась."""


# ── интерфейс ──────────────────────────────────────────────────────────────────
class CallProvider(ABC):
    """Единый контракт звонилки для API-слоя.

    API (`api/calls.py`) знает ТОЛЬКО этот интерфейс — конкретная телефония
    подменяется фабрикой `get_provider()` по env, без правок вызывающего кода.
    """

    name: str = "abstract"

    @abstractmethod
    def originate(self, operator_ext: str, player_phone: str) -> str:
        """Инициировать исходящий звонок: сначала звоним оператору (`operator_ext`),
        после ответа — игроку (`player_phone`). Возвращает `call_ref` (id звонка
        у провайдера) для последующей корреляции с webhook-событием и записью.

        Телефон игрока сюда приходит уже с бэкенда (из ClickHouse), НЕ с фронта.
        """

    @abstractmethod
    def get_recordings(self, call_ref: str) -> list[str]:
        """Список идентификаторов/имён аудиофайлов записи по `call_ref`.
        Пусто — если записи нет/ещё не готова."""

    @abstractmethod
    def stream_recording(self, ref: str) -> Iterator[bytes]:
        """Итератор байтовых чанков аудиозаписи (для стрима в плеер карточки).
        `ref` — либо call_ref, либо конкретное имя файла из `get_recordings`."""

    @abstractmethod
    def health(self) -> bool:
        """Живость провайдера (сессия активна / mock всегда готов)."""


# ==============================================================================
# TegsoftProvider — реальная телефония (UNVERIFIED: без доступа к инстансу клиента)
# ==============================================================================
class TegsoftProvider(CallProvider):
    """Клиент Tegsoft REST (Contact Center + PBX).

    Держит СЕРВИСНУЮ сессию: логинится один раз, продлевает по checkLoginStatus,
    перелогинивается при протухании. Потокобезопасно (Flask多worker) через Lock.

    ВНИМАНИЕ: точные имена сервисов/параметров originate и списка записей в
    публичном дампе доков видны частично (см. tegsoft_docs_raw.txt). Спорные места
    вынесены в env и помечены UNVERIFIED — при получении доступа сверить и снять метку.
    """

    name = "tegsoft"

    def __init__(
        self,
        base_url: str | None = None,
        usercode: str | None = None,
        password: str | None = None,
        token: str | None = None,
        profile: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        retries: int = _DEFAULT_RETRIES,
        verify_tls: bool | None = None,
        agent_call: bool = False,
    ) -> None:
        self.base_url = (base_url or os.environ.get("TEGSOFT_BASE_URL", "")).rstrip("/")
        # env-фолбэк ТОЛЬКО если аргумент None; явная пустая строка = «без этого креда»
        # (напр. token='' + usercode/password оператора → режим performLogin под ним,
        #  а не откат на общий TEGSOFT_TOKEN).
        self._usercode = usercode if usercode is not None else os.environ.get("TEGSOFT_USERCODE", "")
        self._password = password if password is not None else os.environ.get("TEGSOFT_PASSWORD", "")
        self._token = token if token is not None else os.environ.get("TEGSOFT_TOKEN", "")
        # CONTEXTID профиля исходящей кампании (originateWithProfile)
        self.profile = profile or os.environ.get("TEGSOFT_PROFILE_CONTEXTID", "")
        self.timeout = timeout
        self.retries = max(0, retries)
        env_verify = os.environ.get("TEGSOFT_VERIFY_TLS", "true").strip().lower()
        self.verify_tls = verify_tls if verify_tls is not None else env_verify not in ("0", "false", "no", "off")
        # Имена методов вынесены в env (правятся без кода при сверке на боевом инстансе).
        # ПОДТВЕРЖДЕНО по докам (tegsoft_docs_raw.txt): служба `RemotePBX`, флаг записи
        # `__STARTREC=true`, а также метод `bridgeWithAnnouncement` (extension+destination+
        # profile+variables). Простой «Originate Call» берёт extension+destination (без profile).
        # Точное строковое имя метода originate в публичном дампе показано частично → env-дефолт.
        self._svc_originate = os.environ.get("TEGSOFT_ORIGINATE_METHOD", "originateWithProfile")
        self._svc_list_recordings = os.environ.get("TEGSOFT_RECORDINGS_LIST_SERVICE", "getRelatedAudioFileNames")

        if not self.base_url:
            raise CallProviderError("TEGSOFT_BASE_URL не задан — TegsoftProvider недоступен")
        if not (self._token or (self._usercode and self._password)):
            raise CallProviderError("Нужны TEGSOFT_TOKEN или TEGSOFT_USERCODE+TEGSOFT_PASSWORD")

        # agent_call: звонок «от имени агента» (ContactCenterServices/agentCall) —
        # Tegsoft считает, что оператор сам нажал набор → БЕЗ попапа «ответить»
        # (в отличие от PBX-originate). Работает только под токеном самого оператора
        # (USERCODE берём из его сессии). Ход, решивший автоответ на WebRTC-трубке.
        self.agent_call = agent_call
        self._agent_uc = None           # кэш USERCODE/UID агента (из checkLoginStatus)
        self._agent_uid = None
        self._lock = threading.Lock()
        self._session = None            # requests.Session (ленивая инициализация)
        self._logged_in = False

    # ── HTTP-слой ──────────────────────────────────────────────────────────────
    def _requests(self):
        """Ленивый импорт requests — модуль грузится даже без установленной библиотеки
        (важно, чтобы MockProvider/тесты работали в окружении без requests)."""
        try:
            import requests  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover - зависит от окружения
            raise CallProviderError(
                "Библиотека 'requests' не установлена — TegsoftProvider недоступен "
                "(pip install requests). MockProvider работает без неё."
            ) from e
        return requests

    def _get_session(self):
        if self._session is None:
            self._session = self._requests().Session()
            if self._token:
                self._session.headers["Authorization"] = f"Bearer {self._token}"
        return self._session

    def _url(self, servlet: str, params: dict) -> str:
        return f"{self.base_url}/Tobe/view/{servlet}?{urlencode(params)}"

    def _request(self, servlet: str, params: dict, *, stream: bool = False):
        """GET с таймаутом и ретраями. Возвращает requests.Response.
        Ошибки транспорта заворачиваем в TegsoftError (без утечки секретов)."""
        requests = self._requests()
        url = self._url(servlet, params)
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self._get_session().get(
                    url, timeout=self.timeout, verify=self.verify_tls, stream=stream
                )
                if resp.status_code in (401, 403):
                    raise TegsoftAuthError(f"Tegsoft {servlet}: {resp.status_code} (сессия/права)")
                resp.raise_for_status()
                return resp
            except TegsoftAuthError:
                raise
            except requests.RequestException as e:  # таймаут/сеть/HTTP
                last_exc = e
                if attempt < self.retries:
                    time.sleep(_RETRY_BACKOFF * (2 ** attempt))
                    continue
        raise TegsoftError(f"Tegsoft {servlet} недоступен после {self.retries + 1} попыток") from last_exc

    # ── сессия ─────────────────────────────────────────────────────────────────
    def _login(self) -> None:
        """performLogin: usercode+password ИЛИ Bearer token. UNVERIFIED (параметры
        password-логина в публичном дампе видны частично; сверить на боевом инстансе)."""
        params = {"service": "performLogin", "locale": "en"}
        if not self._token:
            params["usercode"] = self._usercode
            params["password"] = self._password  # UNVERIFIED: возможен crypt/POST-form
        resp = self._request("Login", params)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("errorOccurred") is True:
            raise TegsoftAuthError("performLogin: errorOccurred=true (проверьте учётку/доступ Webservice)")
        self._logged_in = True
        logger.info("tegsoft: performLogin ok")

    def _check_login(self) -> bool:
        """checkLoginStatus → жив ли токен/сессия.

        ПОДТВЕРЖДЕНО на боевом инстансе (f81o27, Bearer-токен entegreapi):
        успех = {"success":true,"user":{...}}, отказ = {"success":false,
        "message":"No user login detected"}. Поля errorOccurred в этом ответе
        нет — поддержано как легаси-фолбэк на случай иной версии инстанса.
        """
        try:
            resp = self._request("Login", {"fileName": "login", "service": "checkLoginStatus"})
            data = resp.json() if resp.content else {}
        except TegsoftError:
            return False
        if isinstance(data, dict):
            if "success" in data:
                return data.get("success") is True
            return data.get("errorOccurred") is not True
        return True

    def _ensure_session(self) -> None:
        # ── Токен-режим (боевой, ПОДТВЕРЖДЁН): авторизация stateless — Bearer-токен
        #    едет в каждом запросе (см. _get_session). performLogin НЕ нужен и на
        #    инстансе отвергается (Code:898 «Usercode, Password and token can not be
        #    null»), поэтому его тут НЕ зовём. Живость токена проверяет health().
        if self._token:
            self._logged_in = True
            return
        # ── Password-режим (UNVERIFIED): классическая сессия performLogin+checkLogin.
        with self._lock:
            if self._logged_in and self._check_login():
                return
            self._logged_in = False
            self._login()

    def _agent_ident(self) -> tuple[str, str]:
        """USERCODE и UID агента текущей сессии (для agentCall) — из checkLoginStatus.
        Кэшируем: у токена сессия неизменна. ('', '') если не удалось."""
        if self._agent_uc is not None:
            return self._agent_uc, self._agent_uid
        try:
            u = self._request("Login", {"fileName": "login", "service": "checkLoginStatus"}).json()
            u = u.get("user") or {}
            self._agent_uc = str(u.get("USERCODE") or "")
            self._agent_uid = str(u.get("UID") or "")
        except Exception:  # noqa: BLE001
            self._agent_uc, self._agent_uid = "", ""
        return self._agent_uc, self._agent_uid

    # ── операции интерфейса ─────────────────────────────────────────────────────
    def originate(self, operator_ext: str, player_phone: str) -> str:
        """click-to-call через PBX originateWithProfile. `__STARTREC=true` — включить
        запись. Возвращаем provider call_ref (CALLID/UNIQUEID из ответа либо синтетический).
        UNVERIFIED: точную форму ответа сверить на боевом инстансе.

        `variables` берутся из env TEGSOFT_ORIGINATE_VARS (деф `__STARTREC=true`),
        чтобы БЕЗ редеплоя добавить авто-ответ на плечо оператора и убрать этап
        «снимите трубку» — прямой звонок. Точная переменная авто-ответа зависит от
        софтфона/инстанса (напр. `__SIPADDHEADER=Call-Info: answer-after=0`); задаём
        через env после сверки на боевом Tegsoft."""
        if not player_phone:
            raise CallProviderError("originate: нужен player_phone")
        # Tegsoft набирает номер БЕЗ «+»: lookup отдаёт E.164 («+90…»), а на набор
        # плюс мешает (запрос клиента «звонить без плюса»). Срезаем ведущий «+»
        # (маску для показа оператору это не трогает — она формируется отдельно).
        # TEGSOFT_DIAL_KEEP_PLUS=1 вернёт прежнее поведение, если инстанс захочет «+».
        dial = player_phone if os.environ.get("TEGSOFT_DIAL_KEEP_PLUS", "").strip().lower() \
            in ("1", "true", "yes") else player_phone.lstrip("+")
        self._ensure_session()

        # ── agent-call: звонок ОТ ИМЕНИ агента (без попапа «ответить») ──
        # ContactCenterServices/agentCall с USERCODE агента (из его сессии) — Tegsoft
        # трактует как ручной набор оператора → плечо соединяется сразу. Метод не
        # берёт extension: агент определяется по токену/USERCODE.
        if self.agent_call:
            uc, uid = self._agent_ident()
            if not uc and not uid:
                raise CallProviderError("agentCall: не удалось определить агента (нужен токен оператора)")
            resp = self._request("ServicesGateway", {
                "service": "ContactCenterServices", "method": "agentCall",
                "DIDNUMBER": dial, "USERCODE": uc or "", "UID": uid or "",
            })
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if isinstance(data, dict) and data.get("errorOccurred") is True:
                raise TegsoftError(f"agentCall: {data.get('statusMessage') or 'errorOccurred'}")
            call_ref = _first_present(data, ("CALLID", "UNIQUEID", "callRef")) or f"tg-{uuid.uuid4()}"
            return str(call_ref)

        # ── PBX-originate (запасной путь, под общим entegreapi; даёт попап) ──
        if not operator_ext:
            raise CallProviderError("originate: нужен operator_ext")
        variables = os.environ.get("TEGSOFT_ORIGINATE_VARS", "").strip() or "__STARTREC=true"
        params = {
            "service": "RemotePBX",
            "method": self._svc_originate,
            "extension": operator_ext,
            "destination": dial,
            "variables": variables,
        }
        if self.profile:
            params["profile"] = self.profile
        resp = self._request("ServicesGateway", params)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if isinstance(data, dict) and data.get("errorOccurred") is True:
            raise TegsoftError(f"originate: {data.get('statusMessage') or 'errorOccurred'}")
        call_ref = _first_present(data, ("CALLID", "callId", "UNIQUEID", "uniqueId", "callRef"))
        if not call_ref:
            # ответ без явного id — генерим корреляционный ref (webhook сопоставим по нему)
            call_ref = f"tg-{uuid.uuid4()}"
            logger.warning("tegsoft originate: id звонка не найден в ответе, ref=%s", call_ref)
        return str(call_ref)

    def get_recordings(self, call_ref: str) -> list[str]:
        """Имена аудиофайлов по звонку (Recordings → Get Related Audio File Names).
        UNVERIFIED: имя сервиса вынесено в env TEGSOFT_RECORDINGS_LIST_SERVICE."""
        if not call_ref:
            return []
        self._ensure_session()
        resp = self._request("Recordings", {"service": self._svc_list_recordings, "CALLID": call_ref})
        try:
            data = resp.json()
        except ValueError:
            return []
        # возможные формы ответа: {"audioFileNames":[...]} / {"files":[...]} / [...]
        if isinstance(data, list):
            return [str(x) for x in data]
        if isinstance(data, dict):
            for key in ("audioFileNames", "fileNames", "files", "recordings"):
                val = data.get(key)
                if isinstance(val, list):
                    return [str(x) for x in val]
        return []

    def stream_recording(self, ref: str) -> Iterator[bytes]:
        """Стрим аудио (Recordings → streamAudioFile). `ref` — CALLID (или имя файла)."""
        if not ref:
            raise CallProviderError("stream_recording: пустой ref")
        self._ensure_session()
        # эвристика: имя файла (rec...mp3/.wav) шлём как audioFileName, иначе — как CALLID
        params = {"service": "streamAudioFile"}
        if ref.lower().endswith((".mp3", ".wav", ".gsm", ".ogg")):
            params["audioFileName"] = ref
        else:
            params["CALLID"] = ref
        resp = self._request("Recordings", params, stream=True)
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                yield chunk

    def health(self) -> bool:
        try:
            # Токен-режим: реально бьём checkLoginStatus с Bearer (живость токена).
            if self._token:
                return self._check_login()
            self._ensure_session()
            return True
        except CallProviderError:
            return False


# ==============================================================================
# MockProvider — полный цикл без внешних вызовов
# ==============================================================================
class MockProvider(CallProvider):
    """Разработка/тесты без Tegsoft. Хранит звонки в памяти, умеет сгенерировать
    webhook-событие (`simulate_webhook`) как это сделал бы боевой Tegsoft ECR."""

    name = "mock"

    def __init__(self) -> None:
        self._calls: dict[str, dict] = {}
        self._lock = threading.Lock()

    def originate(self, operator_ext: str, player_phone: str) -> str:
        if not operator_ext or not player_phone:
            raise CallProviderError("originate: нужны и operator_ext, и player_phone")
        call_ref = f"mock-{uuid.uuid4()}"
        with self._lock:
            self._calls[call_ref] = {
                "operator_ext": operator_ext,
                "player_phone": player_phone,   # хранится ТОЛЬКО в mock-памяти, не отдаётся
                "started_at": time.time(),
            }
        logger.info("mock originate: ext=%s → ref=%s", operator_ext, call_ref)
        return call_ref

    def get_recordings(self, call_ref: str) -> list[str]:
        if call_ref not in self._calls:
            return []
        # детерминированное имя записи — как у Tegsoft (rec<ext><ts>.mp3)
        return [f"rec-{call_ref}.mp3"]

    def stream_recording(self, ref: str) -> Iterator[bytes]:
        # крошечный валидный «MP3-ish» payload, чтобы плеер/тест получили байты
        yield b"ID3\x03\x00\x00\x00\x00\x00\x00"
        yield b"MOCK-AUDIO-" + ref.encode("ascii", "ignore")

    def health(self) -> bool:
        return True

    # ── симуляция боевого webhook-события Tegsoft ECR ──────────────────────────
    def build_webhook_payload(
        self,
        call_ref: str,
        outcome: str,
        duration_sec: int,
        *,
        casino_player_id: int | None = None,
        operator_ext: str | None = None,
        recording_ref: str | None = None,
    ) -> dict:
        """Собрать полезную нагрузку webhook так, как её прислал бы Tegsoft ECR
        по завершении звонка. Отдаётся тестам/симулятору для POST на приёмник."""
        rec = self._calls.get(call_ref, {})
        return {
            "provider_ref": call_ref,
            "casino_player_id": casino_player_id,
            "operator_ext": operator_ext or rec.get("operator_ext"),
            "outcome": outcome,
            "duration_sec": duration_sec,
            "recording_ref": recording_ref,
            "started_at": rec.get("started_at"),
            "event": "callEnd",
        }

    def simulate_webhook(
        self,
        call_ref: str,
        outcome: str,
        duration_sec: int,
        *,
        webhook_url: str | None = None,
        secret: str | None = None,
        casino_player_id: int | None = None,
        operator_ext: str | None = None,
        recording_ref: str | None = None,
    ) -> dict:
        """Сгенерировать webhook-событие. Если задан `webhook_url` — сделать реальный
        POST на локальный приёмник (`/api/v1/webhooks/tegsoft`) с shared-secret в заголовке.
        Если URL нет (или requests не установлен) — вернуть payload, чтобы тест дёрнул
        приёмник напрямую через Flask test client. Возвращает dict со статусом."""
        payload = self.build_webhook_payload(
            call_ref, outcome, duration_sec,
            casino_player_id=casino_player_id, operator_ext=operator_ext, recording_ref=recording_ref,
        )
        if not webhook_url:
            return {"posted": False, "payload": payload}
        try:
            import requests  # noqa: PLC0415
        except ImportError:
            return {"posted": False, "payload": payload, "reason": "requests-not-installed"}
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["X-Tegsoft-Secret"] = secret
        resp = requests.post(webhook_url, json=payload, headers=headers, timeout=_DEFAULT_TIMEOUT)
        return {"posted": True, "status_code": resp.status_code, "payload": payload}


# ── утилиты ────────────────────────────────────────────────────────────────────
def _first_present(data: object, keys: tuple[str, ...]) -> object | None:
    if isinstance(data, dict):
        for k in keys:
            if data.get(k):
                return data[k]
        # иногда id лежит в data['result'] / data['ServiceResult']
        for wrap in ("result", "ServiceResult", "data"):
            inner = data.get(wrap)
            if isinstance(inner, dict):
                found = _first_present(inner, keys)
                if found:
                    return found
    return None


# ── фабрика ────────────────────────────────────────────────────────────────────
_provider_singleton: CallProvider | None = None
_provider_lock = threading.Lock()


def get_provider(force: str | None = None) -> CallProvider:
    """Вернуть провайдер по env `CALL_PROVIDER` (mock|tegsoft, default=mock).
    Синглтон (сессия Tegsoft переиспользуется между запросами). `force` — для тестов."""
    global _provider_singleton
    kind = (force or os.environ.get("CALL_PROVIDER", "mock")).strip().lower()
    with _provider_lock:
        if _provider_singleton is not None and _provider_singleton.name == kind and force is None:
            return _provider_singleton
        provider: CallProvider = TegsoftProvider() if kind == "tegsoft" else MockProvider()
        if force is None:
            _provider_singleton = provider
        return provider


def reset_provider() -> None:
    """Сбросить кэш синглтона (тесты / смена env)."""
    global _provider_singleton
    with _provider_lock:
        _provider_singleton = None
