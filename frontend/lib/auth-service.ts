import {
  accountCsrfHeaders,
  djangoAccountService,
  requestAccountApi,
  type AccountSnapshot,
} from "@/lib/account-service";

export type RegistrationInput = {
  username: string;
  email: string;
  password1: string;
  password2: string;
};

export type LoginInput = {
  email: string;
  password: string;
};

async function postCredentials(path: string, input: object): Promise<void> {
  await requestAccountApi<unknown>(path, {
    method: "POST",
    headers: await accountCsrfHeaders(),
    body: JSON.stringify(input),
  });
}

export const djangoAuthService = {
  register(input: RegistrationInput): Promise<void> {
    return postCredentials("/accounts/api/register/", input);
  },
  async signIn(input: LoginInput): Promise<AccountSnapshot> {
    await postCredentials("/accounts/api/login/", input);
    return djangoAccountService.getCurrentAccount();
  },
};
