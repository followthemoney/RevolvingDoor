from openai import OpenAI
import json
# Set your OpenAI API key
import json
from pymongo import MongoClient
import datetime
import json
import re

from logs import LogsWriter
import os

class LLMBatchProcessor:
    def __init__(self, config_path):
        with open(config_path, 'r') as file:
            CONFIG = json.load(file)
        self.CONFIG = CONFIG
        self.logs = LogsWriter(CONFIG)
        self.client = MongoClient(CONFIG['db_url'])
        self.db = self.client[CONFIG['db_name']]
        self.col = self.db['llm']
        self.llm_client = OpenAI(api_key=CONFIG['chatgpt_key'])
        self.ready_batches = []
        self.__batch_check()
        
    def upload_batch(self):
        batch_input_file = self.__upload_batch_file('llm_batch.jsonl')
        self.logs.debug(f"LLM - Batch input file uploaded, file ID: {batch_input_file.id}")
        
        # Step 3: Create the batch request
        batch_job = self.__create_batch(batch_input_file.id)
        
        # Step 4: Upload batch job ID to MongoDB with status 'pending'
        self.col.insert_one({
            "batch_job_id": batch_job.id,
            "status": "pending",
            "created_at": datetime.datetime.utcnow()
        })
        self.logs.debug(f"LLM - Batch job ID {batch_job.id} uploaded to MongoDB with status 'pending'")
    
    def return_ready_batches(self):
        results = []
        processed_results = []
        for batch in self.ready_batches:
            results.append(self.__open_batch(batch))
        self.ready_batches = [] #Reset ready_batches
        for res in results:
            processed_results.append(self.__process_response(res))
        return processed_results
        
    def __process_response(self, data):
        # Parse the file response text
        response_data = data.text.splitlines()

        # Initialize a list to store the results
        results = []

        # Iterate through each line in the response data
        for line in response_data:
            # Parse the JSON object
            data = json.loads(line)
            error = False
            # Check for 'error' and 'status_code'
            if data['error'] is not None:
                error = True
                results.append({'custom_id': custom_id, 'error': error})
                self.logs.error(f"LLM - {custom_id} return fail")
                continue
            if data['response']['status_code'] != 200:
                error = True
                results.append({'custom_id': custom_id, 'error': error})
                self.logs.error(f"LLM - {custom_id} return status code {data['response']['status_code']}")
                continue
            # Extract 'custom_id' and 'content'
            custom_id = data.get('custom_id')
            content = data['response']['body']['choices'][0]['message']['content']
            # Extract the number from the content
            match = re.search(r'\d+', content)
            if match:
                score = int(match.group())
            else:
                score = -1
                self.logs.error(f"LLM - {custom_id} - Did not find a score value for LLM response {content}")
            if score > 100:
                self.logs.error(f"LLM - {custom_id} score above 100 : {score}. LLM response is {content}")
            results.append({'custom_id': custom_id, 'score': score, 'error': error})
            self.logs.debug(f"LLM - {custom_id} added with score {score}")
        return results

    def __batch_check(self):
        self.logs.info(f"LLM - Checking batch status")
        pending_batches = self.col.find({"status": "pending"})
        ready_batches = []
        for batch in pending_batches:
            batch_id = batch["batch_job_id"]
            batch_status = self.llm_client.batches.retrieve(batch_id)
            if batch_status.status == 'validating':
                self.logs.debug(f"LLM - Batch ID: {batch_id} is currently being validated.")
            elif batch_status.status == 'failed':
                self.logs.error(f"LLM - Batch ID: {batch_id} has failed validation.")
                self.col.update_one({"batch_job_id": batch_id}, {"$set": {"status": "failed"}})
            elif batch_status.status == 'in_progress':
                self.logs.debug(f"LLM - Batch ID: {batch_id} is currently in progress.")
            elif batch_status.status == 'finalizing':
                self.logs.debug(f"LLM - Batch ID: {batch_id} is finalizing the results.")
            elif batch_status.status == 'completed':
                self.logs.info(f"LLM - Batch ID: {batch_id} has been completed. Results are ready.")
                output_id = batch_status.output_file_id
                self.col.update_one({"batch_job_id": batch_id}, {"$set": {"status": "completed", "output_file_id": output_id}})
                ready_batches.append(output_id)
            elif batch_status.status == 'expired':
                self.logs.debug(f"LLM - Batch ID: {batch_id} has expired.")
                self.col.update_one({"batch_job_id": batch_id}, {"$set": {"status": "expired"}})
            elif batch_status.status == 'cancelling':
                self.logs.error(f"LLM - Batch ID: {batch_id} is being cancelled.")
            elif batch_status.status == 'cancelled':
                self.logs.error(f"LLM - Batch ID: {batch_id} has been cancelled.")
                self.col.update_one({"batch_job_id": batch_id}, {"$set": {"status": "cancelled"}})
            self.ready_batches = ready_batches
            #print(f"Batch ID: {batch_id}, Status: {batch_status['status']}")

    def __open_batch(self, output_id):
        file_response = self.llm_client.files.content(output_id)
        return file_response

    def __generate_batch_request_data(self, name, page_text, request_id):
        """
        Generates the formatted request for the batch input file.
        """
        prompt = (
            f"I am a journalist investigating instances of 'Revolving Door' scenarios, where former members of the parliament take up positions in industries or organizations related to their former government roles. "
            f"Could you assign a score from 0 to 100 (with 100 being a clear indication of a job change to a new position or company, and 0 being no job change), indicating whether {name} has undergone a job change based on the text below? "
            f"A score closer to 100 should be assigned when a new job title, employer, or sector switch is clearly mentioned. "
            f"If the article likely refers to a person with the same name but not the former parliamentary member, please assign a low score. "
            f"Please answer only the score value and base only the results on this webpage text: {page_text}."
        )
        
        return {
            "custom_id": request_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 4096
            }
        }

    def create_batch_jsonl(self, batch_data, output_file='llm_batch.jsonl'):
        """
        Creates a batch JSONL file from a list of names and page texts.
        Each line is a JSON object representing a batch request.
        """
        # Delete the existing output file if it exists
        if os.path.exists(output_file):
            os.remove(output_file)
        with open(output_file, 'w') as jsonl_file:
            for idx, entry in enumerate(batch_data):
                name = entry['name']
                page_text = entry['page_text']
                request = entry['uuid']
                
                # Generate the request data for each entry
                request_data = self.__generate_batch_request_data(name, page_text, request)
                
                # Write each JSON object as a new line in the JSONL file
                jsonl_file.write(json.dumps(request_data) + '\n')
        
        self.logs.debug(f"LLM - Batch requests saved to {output_file}")

    def __upload_batch_file(self, file_path='llm_batch.jsonl'):
        """
        Uploads the batch input file to OpenAI's API for batch processing.
        """
        with open(file_path, 'rb') as f:
            batch_input_file = self.llm_client.files.create(file=f, purpose='batch')
        return batch_input_file

    def __create_batch(self, batch_input_file_id, description="nightly eval job", completion_window="24h"):
        """
        Creates a batch processing job on OpenAI's API.
        """
        batch = self.llm_client.batches.create(
            input_file_id=batch_input_file_id,
            endpoint="/v1/chat/completions",
            completion_window=completion_window,
            metadata={"description": description}
        )
        return batch
