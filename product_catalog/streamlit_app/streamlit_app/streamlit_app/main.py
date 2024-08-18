import streamlit as st
import time
import requests

backend_url = "http://localhost:8090"

st.title('Chatbot')
response = None
with st.chat_message("assistant"):
    st.write("Hi! How can I help you today?")


if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

def response_generator(input_text):    
    for word in input_text.split():
        yield word + " "
        time.sleep(0.05)

if prompt := st.chat_input("What is up?"):
    # Display user message in chat message container
    with st.chat_message("user"):
        st.markdown(prompt)
    # Add user message to chat history
    response = requests.post(f"{backend_url}/process-user-message/", params={"user_message": prompt})
    print(response.content)
    st.session_state.messages.append({"role": "user", "content": prompt})

if response is not None:
    response = f"{response.content}"

# Display assistant response in chat message container
    with st.chat_message("assistant"):
     st.write_stream(response_generator(response))
# Add assistant response to chat history
    st.session_state.messages.append({"role": "assistant", "content": response})