export type SupportStatus =
  | "NEW"
  | "OPEN"
  | "ASSIGNED"
  | "IN_PROGRESS"
  | "WAITING_FOR_CUSTOMER"
  | "WAITING_FOR_SUPPORT"
  | "ESCALATED"
  | "RESOLVED"
  | "CLOSED"
  | "REOPENED"
  | "SPAM"
  | "ARCHIVED";

export type SupportMessage = {
  sequence: number;
  sender_type: string;
  message_type: string;
  visibility: "PUBLIC" | "AGENT_ONLY";
  body: string;
  created_at: string;
};

export type SupportAttachment = {
  asset_reference: string;
  message_sequence: number;
  filename: string;
  content_type: "image/jpeg" | "image/png" | "image/webp";
  byte_size: number;
  created_at: string;
};

export type SupportConversationSummary = {
  reference: string;
  subject: string;
  status: SupportStatus;
  priority: string;
  channel: string;
  assigned_to_me: boolean;
  assigned: boolean;
  version: number;
  created_at: string;
  updated_at: string;
  first_response_deadline: string | null;
  resolution_deadline: string | null;
};

export type SupportConversationPage = {
  items: SupportConversationSummary[];
  next_cursor: string | null;
};

export type SupportMessagePage = {
  items: SupportMessage[];
  next_cursor: string | null;
};

export type SupportConversationDetail = SupportConversationSummary & {
  messages: SupportMessage[];
  messages_next_cursor: string | null;
};

export type SupportSlaEscalation = {
  reference: string;
  ticket_reference: string;
  ticket_status: SupportStatus;
  priority: string;
  kind: "FIRST_RESPONSE" | "NEXT_RESPONSE" | "RESOLUTION" | "MANUAL";
  phase: "AT_RISK" | "BREACHED" | "MANUAL";
  source: "AUTOMATED" | "MANUAL";
  status: "OPEN" | "ACKNOWLEDGED";
  deadline_at: string | null;
  observed_at: string;
  acknowledged_at: string | null;
  created_at: string;
};