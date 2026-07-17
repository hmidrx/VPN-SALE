export const bucketLabel:Record<string,string>={CASH:'نقدی',REFUND:'بازپرداخت',PROMOTIONAL:'اعتبار تبلیغاتی',REFERRAL:'اعتبار معرفی',GIFT:'هدیه',ADMIN_GRANT:'اعتبار مدیریتی'};
export const statusLabel:Record<string,string>={ACTIVE:'فعال',FROZEN:'مسدود مالی',CLOSED:'بسته',RELEASED:'آزادشده',EXPIRED:'منقضی',CAPTURED:'مصرف‌شده',CANCELLED:'لغوشده',EXHAUSTED:'تمام‌شده',REVERSED:'برگشت‌خورده'};
export function directionLabel(d:string):string{return d==='DEBIT'?'بدهکار (Debit)':'بستانکار (Credit)';}
export function safeCode(code?:string):string{return code ? code.replace(/[^A-Z0-9_.:-]/gi,'').slice(0,80) : 'UNKNOWN';}
