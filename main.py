from typing import Annotated
from fastapi import FastAPI, Depends, Query, HTTPException
import google.generativeai as genai
import uuid
# from fastapi.responses import StreamingResponse\
from sse_starlette.sse import EventSourceResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Field, Session, SQLModel, create_engine, select, Relationship
from newspaper import Article
from dotenv import load_dotenv
import os

# .DOTENV STUFF
load_dotenv()

# GEMINI STUFF
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")


# DB STUFF
# LINK TABLE
class UserNewsContentLink(SQLModel, table=True):
    user_id: str | None = Field(default=None,
                                foreign_key="user.id",
                                primary_key=True)

    news_content_id: str | None = Field(default=None,
                                        foreign_key="newscontent.id",
                                        primary_key=True)


class UserBase(SQLModel):
    email: str = Field(index=True, unique=True)
    password: str


class User(UserBase, table=True):
    id: str | None = Field(primary_key=True, index=True,
                           default_factory=lambda: str(uuid.uuid4()))

    history: list["NewsContent"] = Relationship(
        back_populates="users", link_model=UserNewsContentLink)


class UserDto(UserBase):
    id: str


class UserCreateDto(UserBase):
    pass


class UserUpdateDto(SQLModel):
    email: str | None = None,
    password: str | None = None,
    # history: list[str] | None


class NewsContentBase(SQLModel):
    title: str
    authors: str | None = Field(default=None)
    publication_date: str | None = Field(default=None)
    content: str | None = Field(default=None)
    url: str = Field(index=True, unique=True)


class NewsContent(NewsContentBase, table=True):
    id: str | None = Field(primary_key=True, index=True,
                           default_factory=lambda: str(uuid.uuid4()))

    summary: str | None = Field(default=None)

    # user_id: str = Field(foreign_key="user.id")
    users: list[User] = Relationship(
        back_populates="history", link_model=UserNewsContentLink)


class NewsContentDto(NewsContentBase):
    id: str


class UserWithHistory(UserDto):
    history: list[NewsContent] = []


# DB SETUP
postgres_fname = os.environ.get("POSTGRES_DBNAME")
postgres_username = os.environ.get("POSTGRES_USERNAME")
postgres_password = os.environ.get("POSTGRES_PASSWORD")
postgres_hostname = ""
if os.environ.get("PRODUCTION").lower() == "true":
    postgres_hostname = os.environ.get("DB_SERVICE")
else:
    postgres_hostname = os.environ.get("POSTGRES_HOSTNAME")
postgres_port = os.environ.get("POSTGRES_PORT")
# postgres_url = "postgresql://root:root@localhost:5432/database.db"
postgres_url = f"postgresql://{postgres_username}:{postgres_password}@{
    postgres_hostname}:{postgres_port}/{postgres_fname}"
engine = create_engine(postgres_url)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


session_dep = Annotated[Session, Depends(get_session)]


# APP STUFF
app = FastAPI()


# TYPE


# SETUP
@app.on_event("startup")
def on_startup():
    create_db_and_tables()


# MIDDLEWARE
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"]  # Allows all headers
)


# FUNCTIONS
# NEWS_CONTENTs
async def add_news_content_summary(news_content_id: str,
                                   summary: str,
                                   session: session_dep):
    news_content = session.get(NewsContent, news_content_id)
    if news_content.summary is not None:
        print(f"[add_news_content_summary] Cache hit on {news_content_id}")
        return
    news_content.summary = summary
    session.add(news_content)
    session.commit()


async def gemini_url_summarizer_stream(url: str):
    prompt = f"Rangkum artikel dari url berikut: {url}"
    res = model.generate_content(prompt,
                                 stream=True)
    for chunk in res:
        print(chunk.text)
        print("_" * 80)
        yield str(chunk.text)


async def gemini_content_summarizer_stream(content: str,
                                           finalize_func):
    prompt = f"Rangkum artikel berikut: {content}"
    res = model.generate_content(prompt, stream=True)
    final_res = ""
    for chunk in res:
        final_res = final_res + chunk.text
        yield str(chunk.text)
    await finalize_func(final_res)


async def create_news_content(
    user_id: str,
    data: NewsContent,
    session: session_dep
) -> NewsContent:
    if session.exec(
        select(UserNewsContentLink)
        .where(
            UserNewsContentLink.user_id == user_id,
            UserNewsContentLink.news_content_id == data.id
        )
    ).first():
        print(f"[create_news_content] Cache hit on user: {
              user_id}, news: {data.url}")
        return data

    data.users.append(session.get(User, user_id))
    session.add(data)
    session.commit()
    session.refresh(data)
    return data


async def parsed_news_available(url: str, session: session_dep) -> NewsContent:
    return session.exec(
        select(NewsContent)
        .where(NewsContent.url == url)
    ).first()


async def get_parsed_news(url: str, session: session_dep) -> NewsContent:
    parsed = await parsed_news_available(url, session)
    if parsed:
        print(f"[get_parsed_news] Cache hit on {url}")
        return parsed

    article = Article(url=url, fetch_images=False)
    article.download()
    article.parse()
    return NewsContent(title=article.title,
                       authors=str(", ".join(article.authors)),
                       publication_date=article.publish_date,
                       content=article.text,
                       url=article.url)


async def read_all_news_content(
    session: session_dep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100
) -> list[NewsContent]:
    return session.exec(
        select(NewsContent)
        .offset(offset)
        .limit(limit)
    ).all()


# USER
async def add_user_history(id: str,
                           news_content: NewsContent,
                           session: session_dep):
    user = session.get(User, id)
    news_content.users.append(user)
    session.add(news_content)
    session.commit()
    return news_content


async def is_user_exist(email: str,
                        session: Session = session_dep) -> bool:
    return session.exec(
        select(User)
        .where(User.email == email)
    ).first() is not None


async def read_all_users(
    session: session_dep,
    offset: int = 0,
    limit: Annotated[int, Query(le=100)] = 100
):
    return session.exec(
        select(User)
        .offset(offset)
        .limit(limit)
    ).all()


async def read_user_by_id(id: str, session: session_dep):
    return session.get(User, id)


async def create_user(
    data: UserCreateDto,
    session: session_dep
):
    user_db = User.model_validate(data)
    session.add(user_db)
    session.commit()
    session.refresh(user_db)
    return user_db


async def update_user(id: str, data: UserUpdateDto, session: session_dep):
    user_db = session.get(User, id)
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    user_data = data.model_dump(exclude_unset=True)
    for k, v in user_data.items():
        setattr(user_db, k, v)
    session.add(user_db)
    session.commit()
    session.refresh(user_db)
    return user_db


async def delete_user(
    id: str,
    session: session_dep
) -> dict:
    user = session.get(User, id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    session.delete(user)
    session.commit()
    return {"ok": True}


# CONTROLLER
@app.get("/api/v0/{user_id}/news_contents/analyze-news-url-stream")
async def analyze_controller(user_id: str,
                             news_url: str,
                             session: session_dep):
    if session.get(User, user_id) is None:
        raise HTTPException(status_code=403, detail="Access denied")
    return EventSourceResponse(gemini_url_summarizer_stream(news_url))


# NEWS_CONTENTs
@app.post("/api/v0/{user_id}/news-contents/parse-news-url",
          response_model=NewsContent)
async def get_parsed_news_controller(user_id: str,
                                     news_url: str,
                                     session: session_dep):
    return await create_news_content(user_id,
                                     await get_parsed_news(news_url, session),
                                     session)


@app.post("/api/v0/{user_id}/news_contents/summarize-news-content")
async def get_summarize_news_content(user_id: str,
                                     news_content_id: str,
                                     session: session_dep):
    if session.exec(
            select(UserNewsContentLink)
            .where(
                UserNewsContentLink.user_id == user_id,
                UserNewsContentLink.news_content_id == news_content_id
            )).first() is None:
        raise HTTPException(status_code=404, detail="News content not exist")

    return EventSourceResponse(
        gemini_content_summarizer_stream(
            session.get(NewsContent, news_content_id)
            .content,
            lambda res: add_news_content_summary(news_content_id, res, session)
        )
    )


@app.post("/api/v0/{user_id}/news-contents")
async def create_news_contents_controller(user_id: str, data: NewsContent,
                                          session: session_dep):
    if session.get(User, user_id) is None:
        raise HTTPException(status_code=403, detail="Access denied")
    return await create_news_content(data, session)


@app.get("/api/v0/{user_id}/news-contents", response_model=list[NewsContent])
async def get_all_news_contents_controller(user_id: str, session: session_dep):
    if session.get(User, user_id) is None:
        raise HTTPException(status_code=403, detail="Access denied")
    return await read_all_news_content(session)


# USER
@app.get("/api/v0/users", response_model=list[UserWithHistory])
async def get_all_user_controller(session: session_dep):
    return await read_all_users(session)


@app.get("/api/v0/users/{user_id}", response_model=UserWithHistory)
async def get_user_controller(user_id: str, session: session_dep):
    return await read_user_by_id(user_id, session)


@app.post("/api/v0/users")
async def create_user_controller(new_user: UserCreateDto,
                                 session: session_dep) -> UserDto:
    if session.exec(
        select(User)
        .where(User.email == new_user.email)
    ).first():
        print(f"[create_user_controller] user {new_user.email} already exist")
        raise HTTPException(status_code=409, detail="User already exists")
    return await create_user(new_user, session)


@app.patch("/api/v0/users/{user_id}")
async def update_user_controller(user_id: str,
                                 user_data: UserUpdateDto,
                                 session: session_dep):
    return update_user(user_id, user_data, session)


@app.delete("/api/v0/users/{user_id}")
async def delete_user_controller(user_id: str, session: session_dep):
    return delete_user(user_id, session)


@app.get("/")
async def root():
    return {"message": "Hello World"}
