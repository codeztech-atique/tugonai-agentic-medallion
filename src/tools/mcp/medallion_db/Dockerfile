FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP OK')"
COPY . .
EXPOSE 8000
ENV PORT=8000
ENV CSV_PATH=/app/data/raw_tickets.csv
CMD ["python", "main.py"]
