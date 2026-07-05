from pydantic import BaseModel


class ExportRead(BaseModel):
    format: str
    file_path: str
