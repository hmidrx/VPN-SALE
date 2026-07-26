import type {WebApp} from "./types";
declare global{interface Window{Telegram?:{WebApp?:WebApp}}}
export const getNative=():WebApp|undefined=>typeof window==="undefined"?undefined:window.Telegram?.WebApp;
