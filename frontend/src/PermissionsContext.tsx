import { createContext, useContext } from "react";
import type { UserPermissions } from "./api";

const DEFAULT_OPEN: UserPermissions = {
  username: "",
  ng_admin: true,
  can_access: true,
  can_view_queue: true,
  can_approve: true,
  can_analyze: true,
  can_discover: true,
  can_settings: true,
};

export const PermissionsContext = createContext<UserPermissions>(DEFAULT_OPEN);

export function usePermissions(): UserPermissions {
  return useContext(PermissionsContext);
}
