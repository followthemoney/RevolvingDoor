# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /usr/src/app

# Copy only the necessary files into the container
COPY requirements.txt ./
COPY webUI.py twitter.py rss.py logs.py config.json ./
COPY templates/ /usr/src/app/templates/
COPY static/ /usr/src/app/static/

# Install any Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Make sure config.json remains changeable outside the Docker container
VOLUME [ "/usr/src/app/config.json", "/usr/src/app/twitterpy.log"]

# Expose port 8080 for the webUI inside the container
EXPOSE 8080

# Install cron and supervisor for managing the tasks
RUN apt-get update && apt-get install -y cron supervisor

# Copy the supervisor configuration
COPY supervisor.conf /etc/supervisor/conf.d/supervisor.conf

# Copy the cron configuration
COPY cronfile /etc/cron.d/project-cron

# Set correct permissions for the cronfile
RUN chmod 0644 /etc/cron.d/project-cron

# Apply the cron job
RUN crontab /etc/cron.d/project-cron

# Create the log file to be used by cron
RUN touch /var/log/cron.log
# Give permission to edit json file 
RUN chmod 777 /usr/src/app/config.json

# Run both cron and supervisor when the container starts
CMD cron && supervisord -c /etc/supervisor/supervisord.conf
