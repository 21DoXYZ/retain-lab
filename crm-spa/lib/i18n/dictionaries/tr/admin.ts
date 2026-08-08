/**
 * tr · домен «admin». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const admin: Partial<Messages> = {
  "admin.role.super_admin": "Süper yönetici",
  "admin.role.director": "Direktör",
  "admin.role.head_retention": "Retention başkanı",
  "admin.role.head_department": "Departman başkanı",
  "admin.role.operator": "Operatör",
  "admin.role.vip_manager": "VIP yöneticisi",
  "admin.role.affiliate_manager": "Trafik yöneticisi",
  "admin.role.marketing_manager": "Pazarlama",
  "admin.role.analyst": "Analist",
  "admin.role.finance": "Finans",
  "admin.role.risk_officer": "Risk sorumlusu",
  "admin.role.support": "Destek",
  "admin.role.affiliate": "Ortak",
  "admin.role.viewer": "Misafir",

  "admin.dept.retention": "Elde Tutma",
  "admin.dept.call_center": "Çağrı merkezi",
  "admin.dept.whatsapp": "WhatsApp",

  "admin.users.title": "Kullanıcılar",
  "admin.users.lead":
    "Kullanıcı oluşturma, engelleme, şifre sıfırlama ve oyuncu devri. Her işlem denetim günlüğüne (audit_log) yazılır.",
  "admin.users.createOperator": "",
  "admin.users.createAffiliate": "+ Ortak paneli",

  "admin.users.col.name": "Ad Soyad",
  "admin.users.col.login": "Giriş",
  "admin.users.col.role": "Rol",
  "admin.users.search": "",
  "admin.users.flash.roleChanged": "",
  "admin.users.col.scope": "Departman / kod",
  "admin.users.col.status": "Durum",
  "admin.users.col.actions": "İşlemler",
  "admin.users.status.active": "aktif",
  "admin.users.status.blocked": "engellendi",
  "admin.users.action.block": "Engelle",
  "admin.users.action.unblock": "Engeli kaldır",
  "admin.users.action.password": "Şifre",
  "admin.users.action.delete": "Sil",

  "admin.users.modal.createAffiliateTitle": "Ortak paneli",
  "admin.users.modal.createUserTitle": "Yeni kullanıcı",
  "admin.users.modal.resetTitle": "Şifre sıfırlama",
  "admin.users.modal.deleteTitle": "Oyuncu devriyle birlikte sil",

  "admin.users.btn.cancel": "Vazgeç",
  "admin.users.btn.create": "Oluştur",
  "admin.users.btn.save": "Kaydet",

  "admin.users.field.name": "Ad Soyad",
  "admin.users.field.namePlaceholder": "örneğin, Mehmet Yilmaz",
  "admin.users.field.loginEmail": "Giriş (e-posta)",
  "admin.users.field.loginHint": "girişte kullanılır",
  "admin.users.field.role": "Rol",
  "admin.users.field.dept": "Departman",
  "admin.users.field.affCode": "Ortak kodu",
  "admin.users.field.affCodeHint": "örneğin, AF104",
  "admin.users.field.password": "Şifre",
  "admin.users.field.passwordHint":
    "boş bırakılırsa geçici crm12345 atanır, ilk girişte değiştirilmeli",

  "admin.users.resetBody": "Kullanıcı: {name} ({email})",
  "admin.users.field.newPassword": "Yeni şifre",
  "admin.users.field.newPasswordHint": "en az 6 karakter",
  "admin.users.field.newPasswordPlaceholder": "yeni şifre",

  "admin.users.deleteBody":
    "Siliniyor: {name} ({email}). Bu kullanıcıya atanmış oyuncular seçilen operatöre devredilecek (not ve arama geçmişi oyuncuyla birlikte taşınır).",
  "admin.users.field.reassignTo": "Oyuncuları operatöre devret",
  "admin.users.field.reassignHint":
    "boş bırakılabilir — sıra o zaman basitçe kapanır",
  "admin.users.reassignNone": "— devretme —",

  "admin.users.flash.created": "Kullanıcı oluşturuldu",
  "admin.users.flash.blocked": "Hesap engellendi",
  "admin.users.flash.unblocked": "Hesabın engeli kaldırıldı",
  "admin.users.flash.passwordChanged": "Şifre değiştirildi",
  "admin.users.flash.deleted": "Kullanıcı silindi, oyuncular devredildi",
  "admin.users.flash.errorStatus": "Hata ({status})",
  "admin.users.flash.networkError": "Ağ kullanılamıyor",

  "admin.error.unauthorized": "Oturum açılmamış",
  "admin.error.bad_request": "Hatalı istek",
  "admin.error.name_required": "Ad Soyad girin",
  "admin.error.invalid_email": "Geçerli bir e-posta (giriş) girin",
  "admin.error.unknown_role": "Bilinmeyen rol",
  "admin.error.unknown_department": "Bilinmeyen departman",
  "admin.error.password_too_short": "Şifre en az 6 karakter olmalı",
  "admin.error.affiliate_code_required": "Ortak kodu girin",
  "admin.error.department_required": "Departman seçin",
  "admin.error.role_not_allowed": "Bu rolde kullanıcı oluşturmak için yetkiniz yok",
  "admin.error.email_already_exists": "Bu e-posta ile bir kullanıcı zaten var",
  "admin.error.user_not_found": "Kullanıcı bulunamadı",
  "admin.error.forbidden": "Yetkiniz yok",
  "admin.error.unknown_action": "Bilinmeyen işlem",
  "admin.error.reassign_same_operator": "Kaynak ve hedef operatör aynı",
  "admin.error.reassign_target_not_found": "Devredilecek operatör bulunamadı",
};
