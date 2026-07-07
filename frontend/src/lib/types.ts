export type Account = {
  id: number;
  account_name: string;
  api_id: string;
  api_hash: string;
  proxy?: string | null;
  status: string;
  last_login_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};


