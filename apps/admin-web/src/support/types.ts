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

export type SupportConversationDetail = SupportConversationSummary & {
  messages: SupportMessage[];
};
