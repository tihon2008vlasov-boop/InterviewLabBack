from pydantic import BaseModel, EmailStr, Field, field_validator


def normalize_spaces(value: str) -> str:
    return " ".join(value.strip().split())


def valid_name_part(value: str) -> bool:
    stripped = value.replace("-", "").replace("'", "").replace("’", "").replace(".", "")
    return bool(stripped) and all(character.isalpha() for character in stripped)


class RegisterIn(BaseModel):
    name: str = Field(min_length=3, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    company: str = Field(min_length=2, max_length=100)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Name must be a string")
        normalized = normalize_spaces(str(value))
        parts = normalized.split(" ")
        if len(parts) < 2 or not all(valid_name_part(part) for part in parts):
            raise ValueError("Enter a valid first and last name")
        return normalized

    @field_validator("company", mode="before")
    @classmethod
    def validate_company(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Company name must be a string")
        normalized = normalize_spaces(str(value))
        if not any(character.isalnum() for character in normalized):
            raise ValueError("Company name must contain a letter or number")
        return normalized

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> str:
        return str(value).strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("Password must not contain whitespace")
        if not any(character.islower() and character.isascii() for character in value):
            raise ValueError("Password must contain a lowercase Latin letter")
        if not any(character.isupper() and character.isascii() for character in value):
            raise ValueError("Password must contain an uppercase Latin letter")
        if not any(character.isdigit() and character.isascii() for character in value):
            raise ValueError("Password must contain a number")
        if not any(not character.isalnum() for character in value):
            raise ValueError("Password must contain a special character")
        return value


class LoginIn(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, value: object) -> str:
        return str(value).strip().lower()


class UserOut(BaseModel):
    id: str
    name: str
    email: EmailStr
    role: str
    company: str
    avatar_url: str = ""


class TokenOut(BaseModel):
    token: str
    user: UserOut
