from fastapi import FastAPI, Depends, HTTPException
from sqlmodel import SQLModel, Field, create_engine, Session
from typing import Optional, Annotated, AsyncGenerator
from product_catalog import settings
from contextlib import asynccontextmanager
import json

from datetime import datetime

from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletionMessage, ChatCompletion

from dotenv import load_dotenv, find_dotenv

_ : bool = load_dotenv(find_dotenv()) # read local .env file

class Appointment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    patient_name: str
    appointment_time: datetime
    details: Optional[str] = None


def get_client():
    with OpenAI() as client:
        yield client

connection_string = str(settings.DATABASE_URL).replace(
    "postgresql", "postgresql+psycopg"
)

engine = create_engine(
    connection_string, connect_args={}, pool_recycle=300
)

def create_db_and_tables()->None:
    SQLModel.metadata.create_all(engine)

@asynccontextmanager
async def lifespan(app: FastAPI)-> AsyncGenerator[None, None]:
    print("Creating tables..")
    create_db_and_tables()
    yield

def get_session():
    with Session(engine) as session:
        yield session

app:FastAPI = FastAPI(lifespan=lifespan)

def add_appointment_to_db(patient_name: str, appointment_time: str, details: Optional[str], session: Session):
    appointment = Appointment(
        patient_name=patient_name,
        appointment_time=datetime.fromisoformat(appointment_time),
        details=details
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)
    return appointment

# Create the /create-appointment/ route
@app.post("/create-appointment/")
async def create_appointment(patient_name: str, appointment_time: str, details: Optional[str] = None, session: Session = Depends(get_session)):
    appointment = add_appointment_to_db(
        patient_name=patient_name,
        appointment_time=appointment_time,
        details=details,
        session=session
    )
    return {"message": "Appointment created successfully", "appointment": appointment}
    
@app.post("/process-user-message/")
async def process_user_message(user_message: str, session: Session = Depends(get_session), client: OpenAI = Depends(get_client)):
    try:
        messages = [{"role": "user", "content": user_message}]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add_appointment_to_db",
                    "description": "Add an appointment to the database",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "patient_name": {"type": "string", "description": "The name of the patient"},
                            "appointment_time": {"type": "string", "description": "The time of the appointment"},
                            "details": {"type": "string", "description": "Any additional details about the appointment"}
                        },
                        "required": ["patient_name", "appointment_time"]
                    }
                }
            }
        ]
        
        response: ChatCompletion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )

        response_message: ChatCompletionMessage = response.choices[0].message
        print("* First Response: ", dict(response_message))

        tool_calls = response_message.tool_calls
        print("* First Response Tool Calls: ", tool_calls)

        if tool_calls is not None:
            available_functions = {
                "add_appointment_to_db": add_appointment_to_db
            }
            
            messages.append(response_message)

            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_to_call = available_functions[function_name]
                function_args = json.loads(tool_call.function.arguments)
                function_response = function_to_call(
                    patient_name=function_args.get("patient_name"),
                    appointment_time=function_args.get("appointment_time"),
                    details=function_args.get("details"),
                    session=session
                )
                # Ensure content is a dictionary
                content_dict = {
                    "patient_name": function_response.patient_name,
                    "id": function_response.id,
                    "appointment_time": function_response.appointment_time.isoformat(),  # Convert datetime to ISO format string
                    "details": function_response.details
                }
                messages.append(
                    {
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "name": function_name,
                        "content": content_dict,
                    }
                )

            return {"message": response_message.content}
        
        else:
            return {"message": response_message.content}
    
    except Exception as e:
        print("Error: ", str(e))
        raise HTTPException(status_code=500, detail=str(e))
