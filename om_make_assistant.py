import openai
import time

# Load your API key (make sure it's set in your environment or hardcode if you're feeling spicy)
openai.api_key='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'


# Load system prompt from file
with open("om_training_file_bridge.txt", "r", encoding="utf-8") as f:
    system_prompt = f.read()

# 1. Create the assistant
assistant = openai.beta.assistants.create(
    name="Om",
    instructions=system_prompt,
    model="gpt-4.1"
)

print(f'ASSISTANT ID: {assistant.id}')

# 2. Create a new thread
thread = openai.beta.threads.create()

# 3. Send a hardcoded message to the thread
message = openai.beta.threads.messages.create(
    thread_id=thread.id,
    role="user",
    content="Who is Kludgist?"
)

# 4. Run the assistant on the thread
run = openai.beta.threads.runs.create(
    thread_id=thread.id,
    assistant_id=assistant.id
)

# 5. Poll until complete
while run.status not in ["completed", "failed", "cancelled"]:
    time.sleep(1)
    run = openai.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)

# 6. Fetch and print the latest messages
messages = openai.beta.threads.messages.list(thread_id=thread.id)
for m in reversed(messages.data):
    if m.role == "assistant":
        print("Om:", m.content[0].text.value)
