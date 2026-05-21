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
  return normalizeOfflineQueueState(parseBridgePayload(current.getOfflineQueueState()));
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

export function openNativeExternalUrl(url) {
  const current = bridge();
  if (!current?.openExternalUrl) return { success: false, available: false, message: "Native external-link bridge is not available." };
  return parseBridgePayload(current.openExternalUrl(url || ""));
}

export function removeNativeOfflineAction(id) {
  const current = bridge();
  if (!current?.removeOfflineAction) return { success: false, available: false, message: "Native offline queue bridge is not available." };
  return parseBridgePayload(current.removeOfflineAction(String(id || "")));
}

export function clearNativeOfflineActions() {
  const current = bridge();
  if (!current?.clearOfflineActions) return { success: false, available: false, message: "Native offline queue bridge is not available." };
  return parseBridgePayload(current.clearOfflineActions());
}

export function isNativeBridgeAvailable() {
  return Boolean(bridge());
}

export function getNativeBridgeSummary() {
  const current = bridge();
  return {
    available: Boolean(current),
    hostConfig: Boolean(current?.getHostConfig),
    offlineQueue: Boolean(current?.getOfflineQueueState && current?.enqueueOfflineAction),
    photoCapture: Boolean(current?.capturePhoto),
    push: Boolean(current?.requestPushRegistration),
    location: Boolean(current?.getDeviceLocation),
    navigation: Boolean(current?.openExternalNavigation),
    externalLinks: Boolean(current?.openExternalUrl),
  };
}

function normalizeOfflineQueueState(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  const items = Array.isArray(source.items) ? source.items : [];
  return {
    available: Boolean(source.available ?? true),
    count: Number.isFinite(Number(source.count)) ? Number(source.count) : items.length,
    items,
  };
}
