import { tokens } from "@vpnsale/ui";

export default function Page(): React.ReactElement {
  return <main style={{ background: tokens.color.bg, minHeight: "100vh" }}><meta httpEquiv="refresh" content="0; url=/auth/login" /><a href="/auth/login">ورود مدیر</a></main>;
}
