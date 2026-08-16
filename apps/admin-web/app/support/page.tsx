import React from "react";

import { SupportConsole } from "../../src/support/SupportConsole";
import { SupportSlaInbox } from "../../src/support/SupportSlaInbox";

export default function Page() {
  return (
    <>
      <SupportSlaInbox />
      <SupportConsole />
    </>
  );
}
