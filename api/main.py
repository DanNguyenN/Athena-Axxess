import os
import uuid

from models import Message, Persona, Conversation, User, TextCompletionBody
from scripts import speech, parse
import firebase_admin
from firebase_admin import credentials, firestore
import datetime
from pydub import AudioSegment


cred = credentials.Certificate("./secret.json")
firebase_admin.initialize_app(cred)

db = firestore.client()  # this connects to our Firestore database
collection = db.collection('query-db')  # opens 'query-db' collection

from dotenv import load_dotenv

load_dotenv()  # take environment variables from .env.

from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import openai


prompt_base = "Your goal is to help your patient with their health needs. You can ask them questions, or you can give them advice. You can also ask them to tell you more about their health history. Do not answer any questions that you do not know the answer to. Do not answer questions irrelevant to health care. Prefer referring a patient to healthcare professionals over providing incorrect information. Be sure to be kind and respectful to your patient."

personas: list[Persona] = [
    Persona(id=1, name="Dr. Cole", prompt="You are Dr. Cole, a fun, caring pediatric doctor.", professional_description="Dr. Cole is a fun, caring pediatric doctor. Use this persona for your younger patients."),
    Persona(id=2, name="Dr. Smith", prompt="You are Dr. Smith, a fun, caring geriatric doctor. Be extra nice, as your patients are elderly and would love to have a conversation. Verbally reaffirm your love and care for your patient to increase their comfort.", professional_description="Dr. Smith is a fun, caring geriatric doctor. Perfect for your older patients."),
]

for persona in personas:
    persona.prompt = f"{persona.prompt} {prompt_base}"

conversations: list[Conversation] = [
    Conversation(
        id=0,
        user_id=0,
        messages=[],
    )
]
users: list[User] = [User(id=0, name="Angela Thomas", health_history="", conversations=[], persona=personas[1])]


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def read_root():
    return {"up": True}



@app.get("/persona/list")
async def get_personas() -> list[Persona]:
    return personas



@app.post("/conversation/new")
async def new_conversation(user_id: int) -> Conversation:
    conversation_id = len(conversations)
    conversations.append(Conversation(id=conversation_id, user_id=user_id, messages=[]))
    return conversations[conversation_id]

@app.post("/conversation/{conversation_id}/audio")
async def completion_audio(conversation_id: int, file: UploadFile) -> Conversation:
    path = "./assets/" + str(uuid.uuid4())
    with open(path, "wb") as buffer:
        content = await file.read()
        buffer.write(content)

    audio = AudioSegment.from_file(path)
    new_path = path + ".wav"
    audio.export(
        new_path,
        format="wav",
        # codec="pcm_mulaw",
    )

    os.remove(path)
    text = speech.speech2text(new_path)
    os.remove(new_path)

    return completion_text(conversation_id, str(text))


@app.post("/conversation/{conversation_id}/text")
async def _completion_text(conversation_id: int, body: TextCompletionBody) -> Conversation:
    return completion_text(conversation_id, body.message)

def completion_text(conversation_id: int, message: str) -> Conversation:
    trk = parse.TextRank4Keyword()

    # Analysis
    trk.analyze(message)
    kw = trk.get_keywords()
    kw = '|'.join(kw)
    
    # Sentiment model load in
    model = parse.model_load()
    sentiment = model(message)[0] # type: ignore

    # Query the latest document and retrieve its ID
    # query = collection.order_by('Date', direction=firestore.Query.DESCENDING).limit(1)
    # latest_doc = query[0]
    # latest_doc_id = latest_doc.id
    latest_doc_id = str(uuid.uuid4())
    print(sentiment, kw, message)
    res = collection.document(latest_doc_id).set({
        "Date": datetime.datetime.now(),
        "Keywords": kw,
        "Query": message,
        "Sentiment": sentiment,
        "Risk": 0
    })
        
    convo = conversations[conversation_id]
    user = users[convo.user_id]

    msgs = []

    for m in convo.messages:
        msgs.append({
            "role": m.role,
            "content": m.content
        })

    msgs.append(
        {
            "role": "user",
            "content": message,
            # "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    )
    completion = openai.ChatCompletion.create(messages=[
        {
            "role": "system",
            "content": user.persona.prompt,
            # "timestamp": "0"
        },
        *msgs,
    ], model="gpt-3.5-turbo")
    
    
    msgs.append(completion["choices"][0]["message"]) # type: ignore
    convo.messages = []
    for m in msgs:
        convo.messages.append(Message(role=m["role"], content=m["content"]))
    print(convo)

    return convo