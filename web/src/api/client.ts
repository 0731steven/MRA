import axios from "axios";
import { demoAdapter, isDemoMode } from "@/demo/demoApi";

export const apiClient = axios.create({
  baseURL: "",
  timeout: 30_000,
  withCredentials: true,
  adapter: isDemoMode ? demoAdapter : undefined,
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
