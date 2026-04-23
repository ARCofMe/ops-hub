function parseBridgePayload(raw) {
  if (!raw) return null;
  if (typeof raw === "object") return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return { success: false, message: String(raw) };
  }
}

function bridge() {
  if (typeof window === "undefined") return null;
  return window.FieldDeskNativeBridge || null;
}

export function getNativeHostConfig() {
  const current = bridge();
  if (!current?.getHostConfig) return null;
  return parseBridgePayload(current.getHostConfig());
}

export function getNativeOfflineQueueState() {
  const current = bridge();
  if (!current?.getOfflineQueueState) return { available: false, count: 0, items: [] };
  return parseBridgePayload(current.getOfflineQueueState()) || { available: false, count: 0, items: [] };
}

export function enqueueNativeOfflineAction(actionType, payload) {
  const current = bridge();
  if (!current?.enqueueOfflineAction) return { success: false, available: false, message: "Native offline queue bridge is not available." };
  return parseBridgePayload(current.enqueueOfflineAction(actionType, JSON.stringify(payload || {})));
}

export function captureNativePhoto(label, srId) {
  const current = bridge();
  if (!current?.capturePhoto) return { success: false, available: false, message: "Native photo bridge is not available." };
  return parseBridgePayload(current.capturePhoto(label, String(srId || "")));
}

export function requestNativePushRegistration() {
  const current = bridge();
  if (!current?.requestPushRegistration) return { success: false, available: false, message: "Native push bridge is not available." };
  return parseBridgePayload(current.requestPushRegistration());
}

export function requestNativeLocation() {
  const current = bridge();
  if (!current?.getDeviceLocation) return { success: false, available: false, message: "Native location bridge is not available." };
  return parseBridgePayload(current.getDeviceLocation());
}

export function openNativeNavigation(address) {
  const current = bridge();
  if (!current?.openExternalNavigation) return { success: false, available: false, message: "Native navigation bridge is not available." };
  return parseBridgePayload(current.openExternalNavigation(address || ""));
}

export function isNativeBridgeAvailable() {
  return Boolean(bridge());
}
