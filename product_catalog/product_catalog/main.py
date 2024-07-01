from fastapi import FastAPI

app:FastAPI = FastAPI()

@app.get("/")
def read_root() -> dict[str, str]:
    return {"Hello":"World"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0")