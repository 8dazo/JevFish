<template>
  <button v-if="visible" class="demo-starter" type="button" @click="startDemo">
    <span class="demo-kicker">NO FILE NEEDED</span>
    <span class="demo-title">Try sample simulation →</span>
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { setPendingUpload } from '../store/pendingUpload.js'

const route = useRoute()
const router = useRouter()
const visible = computed(() => route.name === 'Home')

const DEMO_MARKDOWN = `# Northstar AI launch scenario

Northstar AI is a fictional consumer technology company preparing to launch a wearable assistant called Halo.

## People and groups
- Maya Chen, Northstar AI CEO. She is optimistic, direct, and focused on shipping quickly.
- Rafael Ortiz, Northstar safety lead. He supports the product but wants stronger privacy guarantees before launch.
- Priya Nair, technology journalist. She is skeptical of marketing claims and asks for evidence.
- Jordan Blake, early adopter and creator. Jordan is excited by new devices but reacts strongly to privacy concerns.
- Digital Rights Forum, a civil-society group advocating for user privacy and transparent data practices.
- Northstar developer community, generally enthusiastic but sensitive to API restrictions and pricing changes.

## Situation
Three days before launch, an internal FAQ is leaked. It says Halo may temporarily retain short audio snippets to improve personalization. The FAQ also says users can disable retention, but the setting is not enabled by default in the current beta.

Northstar plans to publish a clarification later today. Some employees argue the company should delay launch; others think a delay would create more distrust. Technology reporters and creators are already discussing the leak online.

## Initial public posts
1. Priya Nair: “Northstar’s leaked Halo FAQ raises obvious questions about audio retention. I’ve asked the company what is stored, for how long, and whether users explicitly opt in.”
2. Jordan Blake: “Halo looked incredible in the demo, but audio retention needs a very clear explanation. Waiting to hear what Northstar says.”
`

const DEMO_PROMPT = 'Simulate the first 12 hours of public reaction to the Halo audio-retention leak. Track how the company response, journalists, creators, privacy advocates, and developers influence each other. Focus on whether concern escalates or stabilizes and which messages change the conversation.'

const startDemo = () => {
  const file = new File([DEMO_MARKDOWN], 'jevfish-halo-demo.md', {
    type: 'text/markdown'
  })
  setPendingUpload([file], DEMO_PROMPT)
  router.push({ name: 'Process', params: { projectId: 'new' } })
}
</script>

<style scoped>
.demo-starter {
  position: fixed;
  left: 18px;
  bottom: 18px;
  z-index: 950;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 11px 14px;
  border: 1px solid #111;
  background: #fff;
  color: #111;
  box-shadow: 5px 5px 0 #ff4500;
  cursor: pointer;
  font-family: 'JetBrains Mono', monospace;
  text-align: left;
}

.demo-starter:hover {
  transform: translate(-1px, -1px);
  box-shadow: 6px 6px 0 #ff4500;
}

.demo-kicker {
  color: #777;
  font-size: 8px;
  letter-spacing: 0.12em;
}

.demo-title {
  font-size: 11px;
  font-weight: 800;
}

@media (max-width: 720px) {
  .demo-starter {
    left: 10px;
    bottom: 10px;
  }
}
</style>
