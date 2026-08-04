"use client";

import { useState } from "react";
import {
  AppShell,
  PageHeader,
  Eyebrow,
  Card,
  ChartBox,
  Panel,
  Banner,
  Field,
  SCard,
  SCardGrid,
  Badge,
  LifecycleBadge,
  AccountTypeBadge,
  ActionBadge,
  TierBadge,
  VipBadge,
  BeatsCasinoBadge,
  Pill,
  PillRow,
  Chip,
  ChipBar,
  DataTable,
  Button,
  FormField,
  Input,
  Select,
  DateInput,
  Textarea,
  Tabs,
  Modal,
  Skeleton,
  SkeletonText,
  Spinner,
  EmptyState,
  ErrorState,
  type Column,
  type TableState,
} from "@/components/ui";
import { formatInt, formatMoney, formatMoneyMn, formatDate, formatDateTime } from "@/lib/format";
import { I18nProvider } from "@/lib/i18n";

interface DemoPlayer {
  id: number;
  lifecycle: string;
  vip: number;
  turnover: number;
  net: number;
  lastSeen: string;
}

const DEMO_ROWS: DemoPlayer[] = [
  { id: 808, lifecycle: "active", vip: 5, turnover: 4_120_000, net: 512_000, lastSeen: "2026-06-04T10:12:00Z" },
  { id: 34525, lifecycle: "cooling", vip: 3, turnover: 980_400, net: -42_300, lastSeen: "2026-06-01T18:40:00Z" },
  { id: 37635, lifecycle: "at_risk", vip: 2, turnover: 233_100, net: 9_800, lastSeen: "2026-05-28T08:05:00Z" },
  { id: 41002, lifecycle: "dormant", vip: 0, turnover: 12_400, net: -1_200, lastSeen: "2026-04-11T21:33:00Z" },
  { id: 55511, lifecycle: "churned", vip: 1, turnover: 88_600, net: 0, lastSeen: "2026-03-02T13:20:00Z" },
];

const COLUMNS: Column<DemoPlayer>[] = [
  { key: "id", header: "ID", id: true, render: (r) => r.id },
  { key: "lifecycle", header: "Стадия", align: "left", render: (r) => <LifecycleBadge stage={r.lifecycle} /> },
  { key: "vip", header: "VIP", align: "left", render: (r) => <VipBadge level={r.vip} /> },
  { key: "turnover", header: "Оборот", mono: true, render: (r) => formatMoney(r.turnover) },
  {
    key: "net",
    header: "Net",
    mono: true,
    render: (r) => (
      <span className={r.net > 0 ? "text-pos" : r.net < 0 ? "text-neg" : undefined}>
        {formatMoney(r.net)}
      </span>
    ),
  },
  { key: "seen", header: "Последний визит", mono: true, render: (r) => formatDate(r.lastSeen) },
];

const STATE_TABS = [
  { key: "data", label: "Данные" },
  { key: "loading", label: "Загрузка" },
  { key: "empty", label: "Пусто" },
  { key: "error", label: "Ошибка" },
];

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-2">
      <Eyebrow>{title}</Eyebrow>
      {children}
    </section>
  );
}

export default function UiShowcasePage() {
  const [tableState, setTableState] = useState<TableState>("data");
  const [kpiLoading, setKpiLoading] = useState(false);
  const [chip, setChip] = useState("all");
  const [modalOpen, setModalOpen] = useState(false);
  const [tab, setTab] = useState("overview");

  // Standalone preview route (not under app/(app)), so there is no ambient
  // <I18nProvider> from the app layout. Several ui-kit primitives shown below
  // (Badge, States, Collapsible, Modal, AppShell's own nav labels) now call
  // useT() internally, so this showcase needs its own provider — safe here
  // since this route never nests inside the global one.
  return (
    <I18nProvider>
    <AppShell active="players" role="super_admin">
      <PageHeader
        title="Дизайн-система"
        accent="/dev/ui"
        lead="Эталон компонентов A2 — цвета/шрифты/скругления 1:1 с текущей CRM. Все состояния: data · loading · empty · error."
        right={
          <PillRow>
            <Pill live>live</Pill>
            <Pill>Tailwind v4</Pill>
          </PillRow>
        }
      />

      {/* ---- KPI cards ---- */}
      <Section title="SCard — KPI">
        <div className="mb-3">
          <Button size="sm" variant="ghost" onClick={() => setKpiLoading((v) => !v)}>
            {kpiLoading ? "Показать данные" : "Показать загрузку"}
          </Button>
        </div>
        <SCardGrid>
          <SCard
            label="СУММА СТАВОК"
            value={formatMoneyMn(41_200_000)}
            sub="оборот · 128 400 ставок"
            icon="🎲"
            loading={kpiLoading}
          />
          <SCard
            label="GGR — доход казино"
            value={formatMoneyMn(3_180_000)}
            sub="Ставки − Выигрыши"
            icon="🎯"
            variant="orange"
            loading={kpiLoading}
          />
          <SCard
            label="Net (кэш-нетто)"
            value={formatMoneyMn(-420_000)}
            sub="Deposits − Withdrawals"
            icon="💰"
            variant="cream"
            valueTone="neg"
            loading={kpiLoading}
          />
          <SCard
            label="VIP под риском"
            value={formatInt(37)}
            sub="срочно удержать"
            icon="🚨"
            variant="alert"
            loading={kpiLoading}
          />
        </SCardGrid>
      </Section>

      {/* ---- Buttons ---- */}
      <Section title="Button">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary">Primary (ink)</Button>
          <Button variant="brand">Brand (blue)</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="brand" size="sm">Small</Button>
          <Button variant="primary" loading>Загрузка</Button>
          <Button variant="primary" disabled>Disabled</Button>
        </div>
      </Section>

      {/* ---- Pills & chips ---- */}
      <Section title="Pill · Chip (фильтры)">
        <PillRow className="mb-4">
          <Pill live>активно</Pill>
          <Pill>депозитор</Pill>
          <Pill>90 дней</Pill>
        </PillRow>
        <ChipBar>
          {["all", "vip", "risk", "beats"].map((k) => (
            <Chip key={k} active={chip === k} onClick={() => setChip(k)}>
              {k === "all" ? "все" : k === "vip" ? "🥇 VIP+" : k === "risk" ? "🚨 риск" : "🎯 обыгрывают"}
            </Chip>
          ))}
        </ChipBar>
      </Section>

      {/* ---- Badges ---- */}
      <Section title="Badge — стадии / VIP / тип / действие">
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {["active", "cooling", "at_risk", "dormant", "churned", "never"].map((s) => (
            <LifecycleBadge key={s} stage={s} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          {[0, 1, 2, 3, 4, 5].map((l) => (
            <VipBadge key={l} level={l} />
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <AccountTypeBadge type="service" />
          <AccountTypeBadge type="test_or_service" />
          <AccountTypeBadge type="blocked" />
          <ActionBadge action="SAVE спасать" />
          <ActionBadge action="WINBACK" />
          <ActionBadge action="NUDGE" />
          <ActionBadge action="CONVERT" />
          <ActionBadge action="NURTURE" />
          <TierBadge tier="D" />
        </div>
        <div className="flex flex-wrap items-center gap-3 text-[13.5px]">
          <span>
            ID 808 <BeatsCasinoBadge />
          </span>
          <Badge tone="pos">+12.4%</Badge>
          <Badge tone="neg">-3.1%</Badge>
        </div>
      </Section>

      {/* ---- Table with 4 states ---- */}
      <Section title="DataTable — 4 состояния">
        <div className="mb-3 max-w-md">
          <Tabs tabs={STATE_TABS} value={tableState} onChange={(k) => setTableState(k as TableState)} />
        </div>
        <Panel>
          <DataTable
            columns={COLUMNS}
            rows={DEMO_ROWS}
            getRowKey={(r) => r.id}
            getRowHref={(r) => `/players/${r.id}`}
            state={tableState}
            emptyTitle="Игроки не найдены"
            emptyDescription="Смягчите фильтры или очистите поиск, чтобы увидеть игроков."
            errorDescription="Не удалось получить список игроков из API."
            onRetry={() => setTableState("data")}
          />
        </Panel>
      </Section>

      {/* ---- Forms ---- */}
      <Section title="FormField — ввод">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 max-w-4xl">
          <FormField label="Поиск игрока" hint="ID, телефон или e-mail">
            <Input placeholder="напр. 34525" />
          </FormField>
          <FormField label="Стадия">
            <Select defaultValue="">
              <option value="">все</option>
              <option value="active">активен</option>
              <option value="cooling">остывает</option>
              <option value="at_risk">под риском</option>
            </Select>
          </FormField>
          <FormField label="Дата от">
            <DateInput defaultValue="2026-06-01" />
          </FormField>
          <FormField label="Сумма" error="Введите число" required>
            <Input placeholder="0" defaultValue="abc" />
          </FormField>
        </div>
        <div className="mt-4 max-w-2xl">
          <FormField label="Заметка" hint="видимость по правам роли">
            <Textarea placeholder="оффер не подошёл — предложить релоад-матч" />
          </FormField>
        </div>
      </Section>

      {/* ---- Tabs, Modal ---- */}
      <Section title="Tabs · Modal">
        <Tabs
          tabs={[
            { key: "overview", label: "Обзор" },
            { key: "money", label: "Деньги" },
            { key: "games", label: "Игры" },
            { key: "notes", label: "Заметки" },
          ]}
          value={tab}
          onChange={setTab}
        />
        <div className="text-[13.5px] text-steel mt-3">Активная вкладка: {tab}</div>
        <div className="mt-4">
          <Button variant="brand" onClick={() => setModalOpen(true)}>
            Открыть модалку
          </Button>
        </div>
        <Modal
          open={modalOpen}
          onClose={() => setModalOpen(false)}
          title="Назначить игроков"
          footer={
            <>
              <Button variant="ghost" onClick={() => setModalOpen(false)}>
                Отмена
              </Button>
              <Button variant="brand" onClick={() => setModalOpen(false)}>
                Назначить
              </Button>
            </>
          }
        >
          Выбрано 12 игроков. Режим: <b>разделить между операторами</b>. Действие попадёт в audit_log.
        </Modal>
      </Section>

      {/* ---- Cards, chartbox, banner, field ---- */}
      <Section title="Card · ChartBox · Banner · Field">
        <div className="grid gap-4 lg:grid-cols-2">
          <ChartBox title="Оборот по дням" caption="за выбранный период">
            <div className="h-[120px] grid place-items-center text-stone text-sm">
              [ слот графика echarts ]
            </div>
          </ChartBox>
          <Card>
            <div className="grid gap-2">
              <Field label="Депозиты" value={formatMoney(88_636.51)} />
              <Field label="Выводы" value={formatMoney(42_100)} />
              <Field label="Последний визит" value={formatDateTime("2026-06-04T10:12:00Z")} />
              <Field label="VIP-уровень" value="👑 Royal" />
            </div>
          </Card>
        </div>
        <Banner>
          <b>Подсказка:</b> все компоненты используют токены из <code>globals.css</code> — новые
          экраны собираются из этого набора без новых цветов и шрифтов.
        </Banner>
      </Section>

      {/* ---- Standalone states ---- */}
      <Section title="Состояния — Skeleton · Empty · Error · Spinner">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card>
            <div className="text-[11px] uppercase tracking-wide text-steel mb-3">Skeleton</div>
            <Skeleton className="h-8 w-40 mb-3" />
            <SkeletonText lines={4} />
          </Card>
          <Card padded={false}>
            <EmptyState
              title="Нет заметок"
              description="Добавьте первую заметку по игроку — она появится здесь с автором и временем."
              action={<Button size="sm" variant="brand">Добавить заметку</Button>}
            />
          </Card>
          <Card padded={false}>
            <ErrorState onRetry={() => undefined} />
          </Card>
        </div>
        <div className="flex items-center gap-3 mt-4 text-steel">
          <Spinner /> <span className="text-[13.5px]">Загрузка данных…</span>
        </div>
      </Section>

      {/* ---- Formatters ---- */}
      <Section title="lib/format — числа и деньги">
        <Panel>
          <div className="grid gap-2 p-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="formatInt" value={formatInt(1234567)} />
            <Field label="formatMoney" value={formatMoney(88636.51)} />
            <Field label="formatMoneyMn" value={formatMoneyMn(41200000)} />
            <Field label="formatDate" value={formatDate("2026-06-04T10:12:00Z")} />
            <Field label="formatDateTime" value={formatDateTime("2026-06-04T10:12:00Z")} />
          </div>
        </Panel>
      </Section>

      <div className="h-10" />
    </AppShell>
    </I18nProvider>
  );
}
