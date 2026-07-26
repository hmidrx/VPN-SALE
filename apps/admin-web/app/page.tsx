import { redirect } from "next/navigation";

export default function Page(): React.ReactElement {
  redirect("/auth/login");
}
