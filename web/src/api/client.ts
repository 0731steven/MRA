import axios from "axios";

export const apiClient = axios.create({
  baseURL: "",
  timeout: 30_000,
  withCredentials: true,
});

apiClient.interceptors.response.use(
  response => response,
  error => {
    if (error?.response?.status === 401) {
      window.dispatchEvent(new Event("auth:unauthorized"));
    }
    return Promise.reject(error);
  },
);
