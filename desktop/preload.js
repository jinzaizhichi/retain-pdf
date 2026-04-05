const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("retainPdfDesktop", {
  platform: process.platform,
  onStartupProgress(callback) {
    if (typeof callback !== "function") {
      return () => {};
    }
    const listener = (_event, payload) => callback(payload);
    ipcRenderer.on("startup-progress", listener);
    return () => {
      ipcRenderer.removeListener("startup-progress", listener);
    };
  },
});
