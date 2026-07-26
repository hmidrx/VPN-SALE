import {expect,test} from "@playwright/test";
import {mkdir,readFile,writeFile,access} from "node:fs/promises";
import {createHash} from "node:crypto";
const output="test-results/screenshots";
const scenarios=[
 {name:"customer-desktop",route:"/ui-preview/customer",heading:"نمای کلی حساب من",width:1440,height:900,role:"customer",theme:"dark"},
 {name:"customer-mobile",route:"/ui-preview/customer",heading:"نمای کلی حساب من",width:390,height:844,role:"customer",theme:"dark",safe:true},
 {name:"customer-telegram-dark",route:"/ui-preview/customer",heading:"نمای کلی حساب من",width:390,height:844,role:"customer",theme:"dark",telegram:true,safe:true},
 {name:"customer-telegram-light",route:"/ui-preview/customer",heading:"نمای کلی حساب من",width:390,height:844,role:"customer",theme:"light",telegram:true,safe:true},
 {name:"reseller-desktop",route:"/ui-preview/reseller",heading:"کسب‌وکار فروشندگی من",width:1440,height:900,role:"reseller",theme:"dark"},
 {name:"reseller-mobile",route:"/ui-preview/reseller",heading:"کسب‌وکار فروشندگی من",width:390,height:844,role:"reseller",theme:"dark",safe:true},
 {name:"admin-desktop",route:"/ui-preview/admin",heading:"مرکز عملیات مدیریت",width:1440,height:900,role:"admin",theme:"dark"},
 {name:"admin-mobile",route:"/ui-preview/admin",heading:"مرکز عملیات مدیریت",width:390,height:844,role:"admin",theme:"dark",safe:true},
 {name:"sign-in-preview",route:"/ui-preview/auth/sign-in",heading:"ورود به حساب",width:390,height:844,role:"auth",theme:"dark",form:true},
 {name:"registration-preview",route:"/ui-preview/auth/register",heading:"ساخت حساب جدید",width:390,height:844,role:"auth",theme:"dark",form:true},
 {name:"recovery-method-preview",route:"/ui-preview/auth/recovery-method",heading:"انتخاب روش بازیابی",width:390,height:844,role:"auth",theme:"dark"},
 {name:"email-recovery-preview",route:"/ui-preview/auth/recovery-email",heading:"بازیابی با ایمیل",width:390,height:844,role:"auth",theme:"dark",form:true},
 {name:"telegram-recovery-preview",route:"/ui-preview/auth/recovery-telegram",heading:"بازیابی با تلگرام",width:390,height:844,role:"auth",theme:"dark"},
 {name:"recovery-code-preview",route:"/ui-preview/auth/recovery-code",heading:"بازیابی با کد",width:390,height:844,role:"auth",theme:"dark",form:true},
 {name:"password-reset-preview",route:"/ui-preview/auth/reset-password",heading:"تنظیم رمز عبور تازه",width:390,height:844,role:"auth",theme:"dark",form:true},
 {name:"telegram-link-preview",route:"/ui-preview/auth/telegram-link",heading:"اتصال حساب تلگرام",width:390,height:844,role:"auth",theme:"dark"},
 {name:"active-devices-preview",route:"/ui-preview/auth/devices",heading:"دستگاه‌های فعال",width:390,height:844,role:"auth",theme:"dark"},
 {name:"admin-totp-preview",route:"/ui-preview/auth/admin-totp",heading:"تأیید دومرحله‌ای مدیر",width:390,height:844,role:"admin",theme:"dark",form:true},
 {name:"admin-recovery-codes-preview",route:"/ui-preview/auth/admin-recovery-codes",heading:"کدهای بازیابی مدیر",width:390,height:844,role:"admin",theme:"dark",form:true},
] as const;

test.beforeAll(async()=>mkdir(output,{recursive:true}));
for(const scenario of scenarios)test(scenario.name,async({page})=>{
 const unexpected:string[]=[]; page.on("request",request=>{if(["fetch","xhr"].includes(request.resourceType()))unexpected.push(request.url())});
 await page.setViewportSize({width:scenario.width,height:scenario.height});
 if("telegram" in scenario&&scenario.telegram)await page.addInitScript(({theme})=>{(window as any).Telegram={WebApp:{colorScheme:theme,version:"8.0",themeParams:{bg_color:theme==="dark"?"#11131a":"#f7f8fc"},safeAreaInset:{top:20,bottom:24},contentSafeAreaInset:{top:8,bottom:12},ready(){},expand(){},onEvent(){},offEvent(){}}}}, {theme:scenario.theme});
 await page.goto(scenario.route); await expect(page).toHaveURL(new RegExp(`${scenario.route}$`));
 await page.evaluate(theme=>document.documentElement.dataset.theme=theme,scenario.theme);
 await expect(page.locator("html")).toHaveAttribute("dir","rtl"); await expect(page.getByRole("heading",{name:scenario.heading,exact:true})).toBeVisible();
 if("form" in scenario&&scenario.form)await expect(page.locator("form[data-preview-form]")).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
 expect(await page.evaluate(()=>getComputedStyle(document.documentElement).colorScheme)).toContain(scenario.theme);
 await page.keyboard.press("Tab"); await expect(page.locator(":focus-visible")).toBeVisible();
 if("safe" in scenario&&scenario.safe)await expect(page.locator(".ui-mobile-nav")).toHaveCSS("position","fixed");
 expect(unexpected).toEqual([]); await page.screenshot({path:`${output}/${scenario.name}.png`,fullPage:scenario.role!=="auth",animations:"disabled"});
});

test("auth contracts and honest screenshot regression",async({page})=>{
 await page.goto("/ui-preview/auth/register");
 await expect(page.locator('input[name="username"][autocomplete="username"]')).toHaveCount(1);
 await expect(page.locator('input[autocomplete="new-password"]')).toHaveCount(2);
 await expect(page.locator('input[name="email"]')).not.toHaveAttribute("required","");
 await expect(page.locator('input[type="tel"]')).toHaveCount(0);
 const hashes:Record<string,string>={}; for(const scenario of scenarios){const file=`${output}/${scenario.name}.png`;await access(file);hashes[scenario.name]=createHash("sha256").update(await readFile(file)).digest("hex")}
 expect(hashes["sign-in-preview"]).not.toBe(hashes["registration-preview"]);expect(hashes["customer-desktop"]).not.toBe(hashes["reseller-desktop"]);expect(hashes["reseller-desktop"]).not.toBe(hashes["admin-desktop"]);
 await writeFile(`${output}/manifest.json`,JSON.stringify(scenarios.map(({name,route,width,height,role,theme})=>({file:`${name}.png`,route,viewport:{width,height},role,theme})),null,2));
 const images=await Promise.all(scenarios.map(async s=>({scenario:s,data:(await readFile(`${output}/${s.name}.png`)).toString("base64")})));await page.setViewportSize({width:1200,height:1600});await page.setContent(`<main dir="rtl" style="font-family:Tahoma;background:#0c1019;color:white;padding:24px"><h1>Phase 1A.1.2 · مرور تصویری</h1><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px">${images.map(({scenario:s,data})=>`<figure style="margin:0"><img style="width:100%;height:220px;object-fit:cover;object-position:top;border:1px solid #475569" src="data:image/png;base64,${data}"><figcaption>${s.heading}</figcaption></figure>`).join("")}</div></main>`);await page.screenshot({path:`${output}/contact-sheet.png`,fullPage:true,animations:"disabled"});
});
