import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import { apiClient } from "@/api/client";
import { DEMO_ROLE_KEY, demoUser, isDemoMode } from "@/demo/demoApi";

interface User {
  id: number;
  name: string;
  avatar_url: string | null;
  role: "student" | "teacher";
}

interface AuthState {
  user: User | null;
  loading: boolean;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  isDemo: boolean;
  enterDemo: (role: User["role"]) => void;
}

const AuthContext = createContext<AuthState>(null!);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const handleUnauthorized = () => setUser(null);
    window.addEventListener("auth:unauthorized", handleUnauthorized);
    return () => window.removeEventListener("auth:unauthorized", handleUnauthorized);
  }, []);

  useEffect(() => {
    // Remove tokens created by older builds. Authentication now uses an
    // HttpOnly session cookie that browser scripts cannot read.
    localStorage.removeItem("token");
    if (isDemoMode) {
      const role = localStorage.getItem(DEMO_ROLE_KEY);
      if (role === "student" || role === "teacher") setUser(demoUser(role));
      setLoading(false);
      return;
    }
    apiClient
      .get<User>("/api/auth/me")
      .then((res) => setUser(res.data))
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(): Promise<void> {
    const res = await apiClient.get<User>("/api/auth/me");
    setUser(res.data);
  }

  async function logout() {
    if (isDemoMode) {
      localStorage.removeItem(DEMO_ROLE_KEY);
      setUser(null);
      return;
    }
    try { await apiClient.post("/api/auth/logout"); } finally { setUser(null); }
  }

  function enterDemo(role: User["role"]) {
    localStorage.setItem(DEMO_ROLE_KEY, role);
    setUser(demoUser(role));
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, isDemo: isDemoMode, enterDemo }}>
      {children}
    </AuthContext.Provider>
  );
}
