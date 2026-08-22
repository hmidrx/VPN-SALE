import { tokens } from "@vpnsale/ui";
import { CustomerApp } from "../../src/components/CustomerApp";

export default function Page(): React.ReactElement {
  return <div data-token-bg={tokens.color.bg}><CustomerApp page="home" /></div>;
}
