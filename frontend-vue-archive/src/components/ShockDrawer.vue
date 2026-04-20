<script setup lang="ts">
import { ref, nextTick } from 'vue'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const shockText = ref('')
const isSubmitting = ref(false)
const errorMessage = ref('')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

// Auto-focus textarea when drawer opens
async function onAfterEnter() {
  await nextTick()
  textareaRef.value?.focus()
}

async function submitShock() {
  if (!shockText.value.trim() || isSubmitting.value) return
  isSubmitting.value = true
  errorMessage.value = ''
  try {
    const res = await fetch('/api/simulate/shock', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shock_text: shockText.value.trim() }),
    })
    if (res.ok) {
      shockText.value = ''
      emit('close')
    } else {
      const data = await res.json()
      if (data.detail?.error === 'shock_already_queued') {
        errorMessage.value = 'A shock is already queued.'
      } else if (data.detail?.error === 'no_simulation_running') {
        errorMessage.value = 'No simulation is running.'
      } else {
        errorMessage.value = 'Failed to inject shock.'
      }
    }
  } catch (err) {
    errorMessage.value = 'Network error. Please try again.'
  } finally {
    isSubmitting.value = false
  }
}

function discard() {
  shockText.value = ''
  errorMessage.value = ''
  emit('close')
}
</script>

<template>
  <Transition name="drawer" @after-enter="onAfterEnter">
    <div v-if="open" class="shock-drawer">
      <label class="shock-drawer__label">Inject Market Shock</label>
      <textarea
        ref="textareaRef"
        v-model="shockText"
        class="shock-drawer__textarea"
        placeholder="Describe the shock event..."
        rows="3"
      />
      <p v-if="errorMessage" class="shock-drawer__error">{{ errorMessage }}</p>
      <div class="shock-drawer__actions">
        <button class="shock-drawer__btn shock-drawer__btn--discard" @click="discard">
          Discard Shock
        </button>
        <button
          class="shock-drawer__btn shock-drawer__btn--submit"
          :disabled="!shockText.trim() || isSubmitting"
          @click="submitShock"
        >
          {{ isSubmitting ? 'Injecting...' : 'Inject Shock' }}
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.shock-drawer {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  padding: var(--space-md);
  background-color: var(--color-bg-secondary);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  z-index: 15;
  max-height: 160px;
}

.shock-drawer__label {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-secondary);
}

.shock-drawer__textarea {
  width: 100%;
  max-height: 80px;
  padding: var(--space-xs) var(--space-sm);
  background-color: var(--color-bg-primary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  font-family: var(--font-family);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
  resize: none;
  outline: none;
}
.shock-drawer__textarea:focus {
  border-color: var(--color-accent);
}

.shock-drawer__error {
  font-size: var(--font-size-label);
  font-weight: var(--font-weight-regular);
  color: var(--color-destructive);
}

.shock-drawer__actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

.shock-drawer__btn {
  height: 32px;
  padding: 0 var(--space-md);
  border-radius: 4px;
  font-family: var(--font-family);
  font-size: var(--font-size-label);
  cursor: pointer;
  white-space: nowrap;
}

.shock-drawer__btn--discard {
  background-color: transparent;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  font-weight: var(--font-weight-regular);
}
.shock-drawer__btn--discard:hover {
  background-color: var(--color-border);
}

.shock-drawer__btn--submit {
  background-color: var(--color-accent);
  color: var(--color-text-primary);
  border: none;
  font-weight: var(--font-weight-semibold);
}
.shock-drawer__btn--submit:hover:not(:disabled) {
  background-color: var(--color-accent-hover);
}
.shock-drawer__btn--submit:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* Slide animation */
.drawer-enter-active {
  transition: max-height var(--duration-drawer-enter) ease-out, opacity var(--duration-drawer-enter) ease-out;
}
.drawer-leave-active {
  transition: max-height var(--duration-drawer-exit) ease-in, opacity var(--duration-drawer-exit) ease-in;
}
.drawer-enter-from,
.drawer-leave-to {
  max-height: 0;
  opacity: 0;
  overflow: hidden;
}
</style>
