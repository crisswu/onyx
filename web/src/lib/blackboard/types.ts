export interface BlackboardEntry {
  id: number;
  board_number: number;
  content: string;
  settings: BlackboardSettings;
  created_at: string;
  updated_at: string;
}

export interface BlackboardSummary {
  board_number: number;
  has_content: boolean;
  preview: string;
  updated_at: string;
}

export interface BlackboardSettings {
  fontSize?: number;
  [key: string]: unknown;
}

export interface BlackboardSaveResponse {
  success: boolean;
  message: string;
  updated_at: string;
}
