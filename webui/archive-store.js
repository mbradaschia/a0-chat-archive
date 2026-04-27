import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import { toastFrontendSuccess, toastFrontendError } from "/components/notifications/notification-store.js";

const model = {
  /** @type {Object<string, {archived_at: number, name: string}>} */
  archived: {},

  _observer: null,
  _patched: false,
  _initialized: false,
  _injecting: false,
  _debounceTimer: null,

  async init() {
    if (this._initialized) return;
    this._initialized = true;
    await this._fetchArchived();
    this._patchApplyContexts();
    this._startObserver();
  },

  // ── Data fetching ──────────────────────────────────────────────

  async _fetchArchived() {
    try {
      const res = await callJsonApi("/plugins/chat_archive/get_archived", {});
      if (res?.ok) {
        this.archived = res.archived || {};
      }
    } catch (e) {
      console.error("[chat_archive] Failed to fetch archived:", e);
    }
  },

  // ── Archive operations ─────────────────────────────────────────

  isArchived(chatId) {
    return Object.prototype.hasOwnProperty.call(this.archived, chatId);
  },

  async archiveChat(chatId, chatName) {
    try {
      const res = await callJsonApi("/plugins/chat_archive/archive_chat", {
        chat_id: chatId,
        name: chatName || "",
      });
      if (res?.ok) {
        const updated = { ...this.archived };
        updated[chatId] = { archived_at: res.archived_at, name: chatName || "" };
        this.archived = updated;
        this._filterArchivedFromContexts();
        this._scheduleInject();
        toastFrontendSuccess("Chat archived", "Chat Archive");
      }
    } catch (e) {
      console.error("[chat_archive] Failed to archive:", e);
      toastFrontendError("Failed to archive chat", "Chat Archive");
    }
  },

  async unarchiveChat(chatId) {
    try {
      const res = await callJsonApi("/plugins/chat_archive/unarchive_chat", {
        chat_id: chatId,
      });
      if (res?.ok) {
        const updated = { ...this.archived };
        delete updated[chatId];
        this.archived = updated;
        toastFrontendSuccess("Chat restored", "Chat Archive");
      }
    } catch (e) {
      console.error("[chat_archive] Failed to unarchive:", e);
      toastFrontendError("Failed to restore chat", "Chat Archive");
    }
  },

  async deleteArchivedChat(chatId) {
    try {
      // First: remove from archive.json so ghost entries don't persist
      await callJsonApi("/plugins/chat_archive/unarchive_chat", {
        chat_id: chatId,
      });

      // Then: delete the chat context from the server
      const { sendJsonData } = await import("/index.js");
      await sendJsonData("/chat_remove", { context: chatId });

      // Update local state
      const updated = { ...this.archived };
      delete updated[chatId];
      this.archived = updated;
      toastFrontendSuccess("Chat deleted permanently", "Chat Archive");
    } catch (e) {
      console.error("[chat_archive] Failed to delete:", e);
      toastFrontendError("Failed to delete chat", "Chat Archive");
    }
  },

  // ── applyContexts patch ────────────────────────────────────────

  _patchApplyContexts() {
    if (this._patched) return;
    const chatsStore = Alpine.store("chats");
    if (!chatsStore) return;

    const original = chatsStore.applyContexts.bind(chatsStore);
    const self = this;

    chatsStore.applyContexts = function (contextsList) {
      original(contextsList);
      self._filterArchivedFromContexts();
      self._scheduleInject();
    };

    this._patched = true;

    // Apply immediately to current contexts
    this._filterArchivedFromContexts();
  },

  _filterArchivedFromContexts() {
    const chatsStore = Alpine.store("chats");
    if (!chatsStore) return;

    chatsStore.contexts = chatsStore.contexts.filter(
      (ctx) => !this.isArchived(ctx.id)
    );
  },

  // ── DOM observation + injection ────────────────────────────────

  _startObserver() {
    // Observe the outer container so changes in both the original chats list
    // AND the project_sidebar plugin list (which replaces it) trigger injection.
    const container = document.querySelector(".chats-list-container") ||
                      document.querySelector(".chats-config-list");
    if (!container) {
      setTimeout(() => this._startObserver(), 500);
      return;
    }

    this._observer = new MutationObserver(() => this._scheduleInject());
    this._observer.observe(container, { childList: true, subtree: true });

    this._scheduleInject();
  },

  _scheduleInject() {
    if (this._debounceTimer) clearTimeout(this._debounceTimer);
    this._debounceTimer = setTimeout(() => {
      requestAnimationFrame(() => this._injectAll());
    }, 60);
  },

  _injectAll() {
    if (this._injecting) return;
    this._injecting = true;
    try {
      this._injectArchiveButtons();
      this._injectHeaderButton();
    } finally {
      this._injecting = false;
    }
  },

  // ── Archive buttons per chat row ───────────────────────────────

  _injectArchiveButtons() {
    const containers = document.querySelectorAll(
      ".chats-config-list .chat-container"
    );

    containers.forEach((container) => {
      if (container.querySelector(".archive-btn")) return;

      const li = container.closest("li");
      if (!li) return;

      const chatId =
        li.__x_for_context?.id ||
        li._x_dataStack?.[0]?.context?.id ||
        container.dataset.chatId;
      if (!chatId) return;

      const closeBtn = container.querySelector(
        'button[title="Close chat"]'
      );

      const archiveBtn = document.createElement("button");
      archiveBtn.className = "btn-icon-action chat-list-action-btn archive-btn";
      archiveBtn.title = "Archive chat";
      archiveBtn.dataset.chatId = chatId;

      const icon = document.createElement("span");
      icon.className = "material-symbols-outlined";
      icon.textContent = "archive";
      archiveBtn.appendChild(icon);

      archiveBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        e.preventDefault();
        const nameEl = container.querySelector(".chat-name");
        const chatName = nameEl ? nameEl.textContent.trim() : "";
        this.archiveChat(chatId, chatName);
      });

      if (closeBtn) {
        closeBtn.before(archiveBtn);
      } else {
        container.appendChild(archiveBtn);
      }
    });
  },

  // ── Header "open archive" button ───────────────────────────────

  _injectHeaderButton() {
    if (document.querySelector(".archive-header-btn")) return;

    // Try project_sidebar's visible header row first, fall back to original
    const headerRow =
      document.querySelector(".project-sidebar-container .section-header-row") ||
      document.querySelector(".chats-list-container .section-header-row");
    if (!headerRow) return;

    // project_sidebar uses #newChatProjectSidebar; original sidebar uses #newChat
    const newChatBtn =
      headerRow.querySelector("#newChatProjectSidebar") ||
      headerRow.querySelector("#newChat");
    if (!newChatBtn) return;

    const btn = document.createElement("button");
    btn.className = "archive-header-btn";
    btn.id = "archiveChats";
    btn.title = "View archived chats";
    btn.setAttribute("aria-label", "View archived chats");

    const icon = document.createElement("span");
    icon.className = "material-symbols-outlined";
    icon.textContent = "inventory_2";
    btn.appendChild(icon);

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      if (typeof globalThis.openModal === "function") {
        globalThis.openModal("/plugins/chat_archive/webui/archive-modal.html");
      }
    });

    // Wrap both buttons in a flex container so they group on the right
    const wrapper = document.createElement("div");
    wrapper.className = "archive-header-actions";
    newChatBtn.before(wrapper);
    wrapper.appendChild(btn);
    wrapper.appendChild(newChatBtn);
  },
};

export const store = createStore("chatArchive", model);
