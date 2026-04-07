(function () {
  const panel = document.getElementById("wifiPanel");
  if (!panel) return;

  const wifiListEl = document.getElementById("wifiList");
  const wifiStatusLineEl = document.getElementById("wifiStatusLine");
  const wifiMessageEl = document.getElementById("wifiMessage");
  const wifiSelectedSsidEl = document.getElementById("wifiSelectedSsid");
  const wifiPasswordEl = document.getElementById("wifiPassword");
  const wifiRefreshBtn = document.getElementById("wifiRefreshBtn");
  const wifiConnectBtn = document.getElementById("wifiConnectBtn");
  const wifiDisconnectBtn = document.getElementById("wifiDisconnectBtn");

  let currentNetworks = [];
  let currentSelectedSsid = "";

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setMessage(text, type = "info") {
    wifiMessageEl.textContent = text || "";
    wifiMessageEl.classList.remove("hidden", "success", "error", "info");

    if (!text) {
      wifiMessageEl.classList.add("hidden");
      return;
    }

    wifiMessageEl.classList.add(type);
  }

  function setBusy(isBusy) {
    wifiRefreshBtn.disabled = isBusy;
    wifiConnectBtn.disabled = isBusy;
    wifiDisconnectBtn.disabled = isBusy;
  }

  function setSelectedSsid(ssid) {
    currentSelectedSsid = ssid || "";
    wifiSelectedSsidEl.value = currentSelectedSsid;

    const items = wifiListEl.querySelectorAll(".wifi-network-item");
    for (const item of items) {
      item.classList.toggle("selected", item.dataset.ssid === currentSelectedSsid);
    }

    const selectedNetwork = currentNetworks.find((n) => n.ssid === currentSelectedSsid);
    if (selectedNetwork && selectedNetwork.open) {
      wifiPasswordEl.value = "";
      wifiPasswordEl.placeholder = "Open netwerk - wachtwoord niet nodig";
    } else {
      wifiPasswordEl.placeholder = "WPA/WPA2/WPA3 wachtwoord";
    }
  }

  function renderNetworks(networks) {
    currentNetworks = Array.isArray(networks) ? networks : [];

    if (!currentNetworks.length) {
      wifiListEl.innerHTML = '<div class="wifi-empty">Geen netwerken gevonden</div>';
      return;
    }

    wifiListEl.innerHTML = currentNetworks
      .map((network) => {
        const isSelected = currentSelectedSsid === network.ssid;
        return `
          <button
            type="button"
            class="wifi-network-item ${isSelected ? "selected" : ""}"
            data-ssid="${escapeHtml(network.ssid)}"
          >
            <div class="wifi-network-top">
              <div class="wifi-ssid">${escapeHtml(network.ssid)}</div>
              <div class="wifi-signal">${escapeHtml(network.signal_label || "--")}</div>
            </div>
            <div class="wifi-network-meta">
              <span>${escapeHtml(network.security || "Onbekend")}</span>
              <span>${escapeHtml(String(network.signal_dbm ?? "--"))} dBm</span>
              <span>${escapeHtml(String(network.frequency_mhz ?? "--"))} MHz</span>
            </div>
          </button>
        `;
      })
      .join("");

    const items = wifiListEl.querySelectorAll(".wifi-network-item");
    for (const item of items) {
      item.addEventListener("click", () => {
        const ssid = item.dataset.ssid || "";
        setSelectedSsid(ssid);
      });
    }
  }

  function renderStatus(statusPayload) {
    const status = statusPayload?.status || {};

    if (!statusPayload?.ok) {
      wifiStatusLineEl.textContent = "WiFi-status niet beschikbaar";
      return;
    }

    if (status.connected) {
      const parts = [
        `Verbonden met: ${status.ssid || "--"}`,
        `IP: ${status.ip_address || "--"}`,
        `State: ${status.wpa_state || "--"}`,
      ];
      wifiStatusLineEl.textContent = parts.join(" | ");
      return;
    }

    wifiStatusLineEl.textContent =
      `Niet verbonden | Interface: ${status.interface || "--"} | State: ${status.wpa_state || "--"}`;
  }

  async function loadStatus(silent = false) {
    try {
      const res = await fetch(`/wifi/status?t=${Date.now()}`, { cache: "no-store" });
      const data = await res.json();
      renderStatus(data);

      if (!res.ok && !silent) {
        setMessage(data.message || "Kon wifi-status niet laden", "error");
      }
    } catch (err) {
      if (!silent) {
        setMessage("Kon wifi-status niet laden", "error");
      }
      wifiStatusLineEl.textContent = "WiFi-status niet beschikbaar";
    }
  }

  async function scanNetworks() {
    setBusy(true);
    setMessage("WiFi-scan gestart...", "info");

    try {
      const res = await fetch(`/wifi/networks?t=${Date.now()}`, { cache: "no-store" });
      const data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.message || "WiFi-scan mislukt");
      }

      renderNetworks(data.networks || []);
      setMessage(data.message || "Scan voltooid", "success");

      const selectedExists = currentNetworks.some((n) => n.ssid === currentSelectedSsid);
      if (!selectedExists) {
        setSelectedSsid("");
      }
    } catch (err) {
      renderNetworks([]);
      setMessage(err.message || "WiFi-scan mislukt", "error");
    } finally {
      setBusy(false);
      await loadStatus(true);
    }
  }

  async function connectWifi() {
    const ssid = wifiSelectedSsidEl.value.trim();
    const password = wifiPasswordEl.value;

    if (!ssid) {
      setMessage("Kies eerst een SSID", "error");
      return;
    }

    setBusy(true);
    setMessage(`Verbinden met ${ssid}...`, "info");

    try {
      const res = await fetch("/wifi/connect", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ssid, password }),
      });

      const data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.message || "Verbinden mislukt");
      }

      setSelectedSsid(ssid);
      setMessage(data.message || `Verbonden met ${ssid}`, "success");
      renderStatus(data);
    } catch (err) {
      setMessage(err.message || "Verbinden mislukt", "error");
    } finally {
      setBusy(false);
      await loadStatus(true);
    }
  }

  async function disconnectWifi() {
    setBusy(true);
    setMessage("WiFi-verbinding verbreken...", "info");

    try {
      const res = await fetch("/wifi/disconnect", {
        method: "POST",
      });

      const data = await res.json();

      if (!res.ok || !data.ok) {
        throw new Error(data.message || "Verbreken mislukt");
      }

      wifiPasswordEl.value = "";
      setMessage(data.message || "WiFi-verbinding verbroken", "success");
      renderStatus(data);
    } catch (err) {
      setMessage(err.message || "Verbreken mislukt", "error");
    } finally {
      setBusy(false);
      await loadStatus(true);
    }
  }

  wifiSelectedSsidEl.addEventListener("input", () => {
    currentSelectedSsid = wifiSelectedSsidEl.value.trim();
    setSelectedSsid(currentSelectedSsid);
  });

  wifiRefreshBtn.addEventListener("click", scanNetworks);
  wifiConnectBtn.addEventListener("click", connectWifi);
  wifiDisconnectBtn.addEventListener("click", disconnectWifi);

  loadStatus(true);
  scanNetworks();
  setInterval(() => loadStatus(true), 4000);
})();
