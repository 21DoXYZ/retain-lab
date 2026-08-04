# Tegsoft entegrasyonu — ihtiyacımız olan erişim bilgileri ve ayarlar

_CRM arama modülü (click-to-call, çağrı kayıtları, otomatik çağrı günlüğü) geliştirme tarafında hazırdır.
Devreye alabilmek için Tegsoft tarafında aşağıdaki bilgilere ve ayarlara ihtiyacımız var._

---

## 1. API erişimi (öncelikli)

- **Instance URL** — Tegsoft sunucu adresiniz: `https://<server>.tegsoftcloud.com`
- **Webservice access** yetkisine sahip bir **servis kullanıcısı**:
  - `usercode` (kullanıcı kodu)
  - `password` (şifre)
  - **veya** Bearer `token` — hangisi tercih edilirse

## 2. Giden arama profili (click-to-call için)

- Giden çağrı kampanya profilinin **CONTEXTID** değeri
  (`RemotePBX` / `originateWithProfile` çağrısında kullanılacak)
- Çağrı kaydının otomatik başlaması için `__STARTREC=true` parametresinin
  desteklendiğinin teyidi

## 3. Webhook ayarı (ECR Definitions)

**Contact Center Settings → ECR Definitions** bölümünde tanımlanmasını rica ederiz:

- **Webhook URL:** `https://cas.21do.xyz/api/v1/webhooks/tegsoft`
- **HTTP header:** `X-Tegsoft-Secret: <gizli anahtar — tarafımızdan güvenli kanaldan iletilecek>`
- **Açılması gereken olaylar:** çağrı başlangıcı ve çağrı bitişi
  (süre ve sonuç bilgisi ile birlikte)

## 4. Çağrı kayıtları

- Çağrı kaydı paketinizde/ayarlarınızda **aktif mi**?
- Kayıtların **saklama süresi** ne kadar?
- **Kayıt formatı: stereo (çift kanal — temsilci ve müşteri ayrı) mı, mono (tek karışık kanal) mu?**
  > Not: CRM kartından dinlemek için **mono** yeterlidir. Ancak konuşma analizi
  > (kimin ne söylediğinin ayrıştırılması) için **stereo/çift kanal** gerekmektedir.
  > Mümkünse kayıt profilinin çift kanal olarak ayarlanmasını rica ederiz.
- Kayıt erişimi için kullanılacak servis isimlerinin teyidi:
  `getRelatedAudioFileNames`, `streamAudioFile`

## 5. Temsilci → dahili numara (extension) eşleşmesi

- Her temsilci için dahili numara listesi: `{ temsilci: dahili numara }`
- Varsayılan (default) bir dahili numara tanımlı mı?

## 6. Numara formatı

- Oyuncu telefon numaraları hangi formatta saklanıyor ve aranıyor?
  (örn. `905XXXXXXXXX` / `+905XXXXXXXXX` / `05XXXXXXXXX`)

## 7. CDR (çağrı detay kayıtları) erişimi

- Çağrı süresi ve sonuçları için **CDR tablolarına** (TBLCDR ailesi) okuma erişimi
  sağlanabilir mi? (Alternatif olarak bu bilgileri webhook olaylarından da toplayabiliriz.)

---

### Bizim tarafımızda durum

Adaptör, webhook alıcısı, kayıt dinleme (stream), çağrı–oyuncu eşleştirmesi, numara maskeleme,
rol bazlı erişim ve denetim (audit) **hazırdır**. Yukarıdaki bilgiler tamamlandığında tek satır
ayar değişikliği (`CALL_PROVIDER=tegsoft`) ile devreye alıyoruz; ardından bir test çağrısı yapıp
`CALLID` dönüşünü ve webhook akışını birlikte doğrulayabiliriz.

Teşekkürler.
