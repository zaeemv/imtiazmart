from fastapi import FastAPI, Depends
from sqlmodel import SQLModel, Field, create_engine, Session
from typing import Optional, Annotated, AsyncGenerator
from product_catalog import settings
from contextlib import asynccontextmanager

import asyncio
from aiokafka import AIOKafkaConsumer
from aiokafka import AIOKafkaProducer

class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str
    price: float
    quantity: int

connection_string = str(settings.DATABASE_URL).replace(
    "postgresql", "postgresql+psycopg"
)

engine = create_engine(
    connection_string, connect_args={}, pool_recycle=300
)

def create_db_and_tables()->None:
    SQLModel.metadata.create_all(engine)

async def consume_messages(topic: str, bootstrap_servers: str) -> None:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id="my-group",
        auto_offset_reset='earliest')
    # Get cluster layout and join group `my-group`
    await consumer.start()
    try:
        # Consume messages
        async for msg in consumer:
            print("consumed: ", msg.topic, msg.partition, msg.offset,
                  msg.key, msg.value, msg.timestamp)
    finally:
        # Will leave consumer group; perform autocommit if enabled.
        await consumer.stop()

@asynccontextmanager
async def lifespan(app: FastAPI)-> AsyncGenerator[None, None]:
    print("Creating tables..")
    task = asyncio.create_task(consume_messages('quickstart-events', 'kafka:19092'))
    create_db_and_tables()
    yield

def get_session():
    with Session(engine) as session:
        yield session

async def get_kafka_producer():
    producer = AIOKafkaProducer(
        bootstrap_servers='kafka:19092')
    # Get cluster layout and initial topic/partition leadership information
    await producer.start()
    try:
        # Produce message
        yield producer
    finally:
        # Wait for all pending messages to be delivered or expire.
        await producer.stop()


app:FastAPI = FastAPI(lifespan=lifespan)

@app.get("/")
def read_root() -> dict[str, str]:
    return {"Hello":"World"}


@app.post("/products/", response_model=Product)
async def create_product(product: Product, session: Annotated[Session, Depends(get_session)], producer: Annotated[AIOKafkaProducer, Depends(get_kafka_producer)])->Product:
    session.add(product)
    session.commit()
    session.refresh(product)
    await producer.send_and_wait("quickstart-events", product.json().encode())
    return product

@app.get("/hello/")
def read_hello() -> dict[str, str]:
    return {"Cookie":"Mania"}