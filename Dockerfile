# Use python 3.9 as the base image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy requirements first (to optimize build speed)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port your app runs on
EXPOSE 5000

# Command to run your app
CMD ["python", "app.py"]