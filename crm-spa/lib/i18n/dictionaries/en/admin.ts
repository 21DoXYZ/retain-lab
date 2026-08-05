/**
 * en · домен «admin». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const admin: Partial<Messages> = {
  "admin.role.super_admin": "Super admin",
  "admin.role.director": "Director",
  "admin.role.head_retention": "Head of retention",
  "admin.role.head_department": "Head of department",
  "admin.role.operator": "Operator",
  "admin.role.vip_manager": "Power user manager",
  "admin.role.affiliate_manager": "Traffic manager",
  "admin.role.marketing_manager": "Marketing",
  "admin.role.analyst": "Analyst",
  "admin.role.finance": "Finance",
  "admin.role.risk_officer": "Risk officer",
  "admin.role.support": "Support",
  "admin.role.affiliate": "Affiliate",
  "admin.role.viewer": "Viewer",

  "admin.dept.retention": "Retention",
  "admin.dept.call_center": "Call center",
  "admin.dept.whatsapp": "WhatsApp",

  "admin.users.title": "Users",
  "admin.users.lead":
    "Create, block, reset password and reassign users. Every action is written to the audit log.",
  "admin.users.createOperator": "+ Create operator",
  "admin.users.createAffiliate": "+ Affiliate cabinet",

  "admin.users.col.name": "Name",
  "admin.users.col.login": "Login",
  "admin.users.col.role": "Role",
  "admin.users.col.scope": "Department / code",
  "admin.users.col.status": "Status",
  "admin.users.col.actions": "Actions",
  "admin.users.status.active": "active",
  "admin.users.status.blocked": "blocked",
  "admin.users.action.block": "Block",
  "admin.users.action.unblock": "Unblock",
  "admin.users.action.password": "Password",
  "admin.users.action.delete": "Delete",

  "admin.users.modal.createAffiliateTitle": "Affiliate cabinet",
  "admin.users.modal.createUserTitle": "New user",
  "admin.users.modal.resetTitle": "Reset password",
  "admin.users.modal.deleteTitle": "Delete with user reassignment",

  "admin.users.btn.cancel": "Cancel",
  "admin.users.btn.create": "Create",
  "admin.users.btn.save": "Save",

  "admin.users.field.name": "Name",
  "admin.users.field.namePlaceholder": "e.g. Mehmet Yilmaz",
  "admin.users.field.loginEmail": "Login (e-mail)",
  "admin.users.field.loginHint": "used to sign in",
  "admin.users.field.role": "Role",
  "admin.users.field.dept": "Department",
  "admin.users.field.affCode": "Affiliate code",
  "admin.users.field.affCodeHint": "e.g. AF104",
  "admin.users.field.password": "Password",
  "admin.users.field.passwordHint":
    "leave empty for a temporary crm12345, change it on first login",

  "admin.users.resetBody": "User: {name} ({email})",
  "admin.users.field.newPassword": "New password",
  "admin.users.field.newPasswordHint": "at least 6 characters",
  "admin.users.field.newPasswordPlaceholder": "new password",

  "admin.users.deleteBody":
    "Deleting: {name} ({email}). Their assigned users will be reassigned to the chosen operator (notes and call history move with the user).",
  "admin.users.field.reassignTo": "Reassign users to operator",
  "admin.users.field.reassignHint":
    "can be left empty - the queue will simply close",
  "admin.users.reassignNone": " -  don't reassign - ",

  "admin.users.flash.created": "User created",
  "admin.users.flash.blocked": "Account blocked",
  "admin.users.flash.unblocked": "Account unblocked",
  "admin.users.flash.passwordChanged": "Password changed",
  "admin.users.flash.deleted": "User deleted, assigned users reassigned",
  "admin.users.flash.errorStatus": "Error ({status})",
  "admin.users.flash.networkError": "Network unavailable",

  "admin.error.unauthorized": "Not authenticated",
  "admin.error.bad_request": "Invalid request",
  "admin.error.name_required": "Enter a name",
  "admin.error.invalid_email": "Enter a valid e-mail (login)",
  "admin.error.unknown_role": "Unknown role",
  "admin.error.unknown_department": "Unknown department",
  "admin.error.password_too_short": "Password must be at least 6 characters",
  "admin.error.affiliate_code_required": "Enter an affiliate code",
  "admin.error.department_required": "Select a department",
  "admin.error.role_not_allowed": "Not enough rights to create a user with this role",
  "admin.error.email_already_exists": "A user with this e-mail already exists",
  "admin.error.user_not_found": "User not found",
  "admin.error.forbidden": "Not enough rights",
  "admin.error.unknown_action": "Unknown action",
  "admin.error.reassign_same_operator": "Source and destination operator are the same",
  "admin.error.reassign_target_not_found": "Reassignment target operator not found",
};
