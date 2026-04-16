<script lang="ts">
import { reactive } from 'vue'

export interface ChatMessage {
  role: 'user' | 'agent'
  content: string
}

// Module-level reactive Map — persists across mount/unmount of InterviewPanel (D-05).
// Using reactive(new Map()) instead of plain Map so Vue tracks mutations (addresses Codex MEDIUM).
const allConversations: Map<string, ChatMessage[]> = reactive(new Map())
</script>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'

const props = defineProps<{ agentId: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const input = ref('')
const loading = ref(false)
const errorMessage = ref<string | null>(null)
const chatContainer = ref<HTMLElement | null>(null)

const messages = computed<ChatMessage[]>(() => allConversations.get(props.agentId) ?? [])

// Agent name: "A_01" -> "Agent 01" (same logic as AgentSidebar)
const agentName = computed(() => {
  const num = props.agentId.replace(/\D/g, '')
  return `Agent ${num.padStart(2, '0')}`
})

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  })
}

async function sendMessage() {
  const text = input.value.trim()
  if (!text || loading.value) return

  if (!allConversations.has(props.agentId)) {
    allConversations.set(props.agentId, [])
  }
  const history = allConversations.get(props.agentId)!

  // Optimistic UI: append user message immediately
  history.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  errorMessage.value = null
  scrollToBottom()

  try {
    // encodeURIComponent addresses Codex MEDIUM: safe URL construction
    const res = await fetch(`/api/interview/${encodeURIComponent(props.agentId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })
    if (!res.ok) {
      if (res.status === 404) {
        errorMessage.value = 'Agent not found in simulation data.'
      } else if (res.status === 409) {
        errorMessage.value = 'Interviews are only available after a simulation completes.'
      } else if (res.status === 422) {
        errorMessage.value = 'Message must be 1-4000 characters.'
      } else if (res.status === 503) {
        errorMessage.value = 'Could not reach the server. Try again.'
      } else {
        errorMessage.value = 'Interview failed. Try sending again.'
      }
      return
    }
    const data = await res.json()
    history.push({ role: 'agent', content: data.response })
    scrollToBottom()
  } catch {
    errorMessage.value = 'Could not reach the server. Try again.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="interview-panel">
    <!-- Header -->
    <div class="interview-panel__header">
      <h2 class="interview-panel__title">{{ agentName }}</h2>
      <button class="interview-panel__close" @click="emit('close')" aria-label="Close interview">X</button>
    </div>

    <!-- Chat area -->
    <div class="interview-panel__chat" ref="chatContainer">
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="message"
        :class="msg.role === 'user' ? 'message--user' : 'message--agent'"
      >
        {{ msg.content }}
      </div>
      <div v-if="loading" class="interview-panel__thinking">Thinking...</div>
    </div>

    <!-- Input row -->
    <div class="interview-panel__input-row">
      <textarea
        v-model="input"
        class="interview-panel__textarea"
        placeholder="Ask about their decisions..."
        :disabled="loading"
        @keydown.enter.exact.prevent="sendMessage"
        rows="1"
      />
      <button
        class="interview-panel__send"
        :disabled="loading || !input.trim()"
        @click="sendMessage"
      >
        {{ loading ? '...' : 'Send' }}
      </button>
    </div>

    <!-- Inline error -->
    <div v-if="errorMessage" class="interview-panel__error">
      {{ errorMessage }}
    </div>
  </div>
</template>

<style scoped>
.interview-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: var(--sidebar-width);
  height: 100vh;
  background-color: var(--color-bg-secondary);
  border-left: 1px solid var(--color-border);
  z-index: 10;
  display: flex;
  flex-direction: column;
  padding: var(--space-md);
}

.interview-panel__header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: var(--space-md);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.interview-panel__title {
  font-size: var(--font-size-heading);
  font-weight: var(--font-weight-semibold);
  line-height: var(--line-height-heading);
  color: var(--color-text-primary);
  margin: 0;
}

.interview-panel__close {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 16px;
  padding: var(--space-sm);
  cursor: pointer;
  line-height: 1;
}

.interview-panel__close:hover {
  color: var(--color-accent);
}

.interview-panel__chat {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-md) 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}

.message {
  max-width: 85%;
  padding: var(--space-sm) var(--space-md);
  font-size: var(--font-size-body);
  font-weight: var(--font-weight-regular);
  line-height: var(--line-height-body);
  color: var(--color-text-primary);
  word-break: break-word;
}

.message--user {
  background: rgba(59, 130, 246, 0.15);
  border-radius: 8px 8px 2px 8px;
  align-self: flex-end;
}

.message--agent {
  background: var(--color-bg-primary);
  border-radius: 8px 8px 8px 2px;
  align-self: flex-start;
}

.interview-panel__thinking {
  align-self: flex-start;
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  color: var(--color-text-muted);
  animation: thinking-pulse 1.5s ease-in-out infinite;
}

@keyframes thinking-pulse {
  0%, 100% { opacity: 0.4; }
  50% { opacity: 1.0; }
}

.interview-panel__input-row {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-sm) 0;
  border-top: 1px solid var(--color-border);
  flex-shrink: 0;
}

.interview-panel__textarea {
  flex: 1;
  min-height: 36px;
  max-height: 72px;
  padding: var(--space-xs) var(--space-sm);
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  color: var(--color-text-primary);
  resize: none;
  outline: none;
}

.interview-panel__textarea::placeholder {
  color: var(--color-text-muted);
}

.interview-panel__textarea:focus {
  border-color: var(--color-accent);
}

.interview-panel__send {
  width: 48px;
  height: 36px;
  background: var(--color-accent);
  border: none;
  border-radius: 4px;
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  cursor: pointer;
  flex-shrink: 0;
}

.interview-panel__send:hover:not(:disabled) {
  background: var(--color-accent-hover);
}

.interview-panel__send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.interview-panel__error {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  color: var(--color-destructive);
  padding: var(--space-xs) 0;
}
</style>
