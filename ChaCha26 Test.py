from openai import OpenAI
  
# API configuration
api_key = '90718c8494d63cf613bd4a4d62534b3b' # Replace with your API key
base_url = "https://chat-ai.academiccloud.de/v1"
model = "meta-llama-3.1-8b-instruct" # Choose any available model
  
# Start OpenAI client
client = OpenAI(
    api_key = api_key,
    base_url = base_url
)
  
# Get response
chat_completion = client.chat.completions.create(
        messages=[{"role":"system","content":"You are a helpful assistant"},{"role":"user","content":"How tall is the Eiffel tower?"}],
        model= model,
    )
  
# Print full response as JSON
print(chat_completion) # You can extract the response text from the JSON object
print(chat_completion.choices[0].message.content)