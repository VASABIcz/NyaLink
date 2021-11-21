FROM python:3.10

WORKDIR /app

COPY ./requirements.txt requirements.txt

RUN python -m pip install --upgrade pip

RUN pip install -r requirements.txt

COPY . .

CMD python main.py