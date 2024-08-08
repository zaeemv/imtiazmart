from fastapi import FastAPI, Depends, HTTPException
from sqlmodel import SQLModel, Field, create_engine, Session
from sqlalchemy.future import select
from typing import Optional, Annotated, AsyncGenerator
from product_catalog import settings
from contextlib import asynccontextmanager
import json

from datetime import datetime

from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletionMessage, ChatCompletion
from dotenv import load_dotenv, find_dotenv
from openai.types.beta import Assistant
from openai.types.beta.thread import Thread
from openai.types.beta.threads.run import Run


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

def remove_appointment_from_db(patient_name: str, session: Session):
    statement = select(Appointment).where(Appointment.patient_name == patient_name)
    result = session.execute(statement)
    appointment = result.scalar_one_or_none()

    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")

    session.delete(appointment)
    session.commit()

    return {"patient_name": appointment.patient_name, "id": appointment.id}

def serialize_appointment(appointment):
    return {
        'appointment_time': appointment.appointment_time.isoformat(),
        'details': appointment.details,
        'id': appointment.id,
        'patient_name': appointment.patient_name
    }

# Create the /create-appointment/ route
@app.post("/create-appointment/")
async def add_appointment_to_db(patient_name: str, appointment_time: str, details: Optional[str] = None, session: Session = Depends(get_session)):
    appointment = Appointment(
        patient_name=patient_name,
        appointment_time=datetime.fromisoformat(appointment_time),
        details=details
    )
    session.add(appointment)
    session.commit()
    session.refresh(appointment)
    return {"message": "Appointment created successfully", "appointment": appointment}
    
@app.post("/process-user-message/")
async def process_user_message(user_message: str, session: Session = Depends(get_session), client: OpenAI = Depends(get_client)):
    try:
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
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_appointment_from_db",
                    "description": "Remove an appointment from the database",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "patient_name": {"type": "string", "description": "The name of the patient"},
                        },
                        "required": ["patient_name"]
                    }
                }
            }
        ]
        
        assistant = client.beta.assistants.create(
            instructions="You are a doctor who needs to manage appointments for your patients. You can add or remove appointments from the database.",
            model="gpt-4o-mini",
            tools=tools
        )

        thread = client.beta.threads.create()
        print("* Thread: ", dict(thread))

        message = client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_message,
        )

        run = client.beta.threads.runs.create_and_poll(
            thread_id=thread.id,
            assistant_id=assistant.id,
        )
        
        available_functions = {
            "add_appointment_to_db": add_appointment_to_db,
            "remove_appointment_from_db": remove_appointment_from_db
        }
        import time
        import json

        def show_json(message, obj):
            print(message, json.loads(obj.model_dump_json()))
    # Loop until the run completes or requires action
        while True:
            runStatus = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
            # Add run steps retrieval here for debuging
            run_steps = client.beta.threads.runs.steps.list(thread_id=thread.id, run_id=run.id)
            # show_json("Run Steps:", run_steps)
            print(runStatus.status ,'.....')

            # This means run is making a function call   
            if runStatus.status == "requires_action":
                print(runStatus.status ,'.....')
                print("Status: ", "requires_action")
                show_json("submit_tool_outputs", runStatus.required_action)
                if runStatus.required_action.submit_tool_outputs and runStatus.required_action.submit_tool_outputs.tool_calls:
                    print("toolCalls present:")
                    toolCalls = runStatus.required_action.submit_tool_outputs.tool_calls

                    tool_outputs = []
                    for toolcall in toolCalls:
                        print("HERE 1")
                        function_name = toolcall.function.name
                        function_args = json.loads(toolcall.function.arguments)
                        print("HERE 2")
                        if function_name in available_functions:
                            
                            print("HERE 3")
                            function_to_call = available_functions[function_name]
                            print(function_to_call,function_to_call.__name__=="add_appointment_to_db","================================================================")
                            print("HERE 4")
                            if function_to_call.__name__ == "add_appointment_to_db":
                                print("HERE 5")
                                response = await function_to_call(
                                    patient_name=function_args.get("patient_name"),
                                    appointment_time=function_args.get("appointment_time"),
                                    details=function_args.get("details"),
                                    session=session
                                )
                                
                                
                                tool_outputs.append({
                                        "tool_call_id": toolcall.id,
                                        "output": response
                                    })
                                print("HERE 6")
                            elif function_to_call.__name__ == "remove_appointment_from_db":
                                response = await function_to_call(
                                    patient_name=function_args.get("patient_name"),
                                    session=session
                                )
                                tool_outputs.append({
                                "tool_call_id": toolcall.id,
                                "output": response,
                                    })
                    print("HERE 7")
                    print(tool_outputs,">>>>>")
                    print("HERE 8") 
                    # Submit tool outputs and update the run

                    tool_outputs = [
                        {
                            'tool_call_id': tool_output['tool_call_id'],
                            'output': json.dumps({
                                'message': 'Appointment created successfully',
                                'appointment': serialize_appointment(tool_output['output']['appointment'])
                            })
                        }
                        for tool_output in tool_outputs
                    ]
                    
                    client.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread.id,
                        run_id=run.id,
                        tool_outputs=tool_outputs)
                    print("HERE 9") 
            elif runStatus.status == "completed":
                # List the messages to get the response
                print("completed...........logic")
                messages: list[ThreadMessage] = client.beta.threads.messages.list(thread_id=thread.id)
                for message in messages.data:
                    role_label = "User" if message.role == "user" else "Assistant"
                    message_content = message.content[0].text.value
                    print(f"{role_label}: {message_content}\n")
                break  # Exit the loop after processing the completed run

            elif run.status == "failed":
                print("Run failed.")
                break

            elif run.status in ["in_progress", "queued"]:
                print(f"Run is {run.status}. Waiting...")
                time.sleep(5)  # Wait for 5 seconds before checking again

            else:
                print(f"Unexpected status: {run.status}")
                break
    
    except Exception as e:
        print("Error: ", str(e))
        raise HTTPException(status_code=500, detail=str(e))

