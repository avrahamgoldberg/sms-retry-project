# SMS Retry Scheduler (Python)

A production-ready, resilient SMS retry scheduler with S3 persistence, built for AWS deployment.

## Architecture

### Core Data Structures

1. **heapq (Priority Queue)**: Python's built-in min-heap for time-based scheduling
   - O(log n) inserts via `heapq.heappush()`
   - O(1) peek with `heap[0]`
   - O(log n) pop with `heapq.heappop()`

2. **Dict (Hash Map)**: Fast message state lookup by ID
   - O(1) average-case lookups
   - Thread-safe when protected by RLock

3. **threading.RLock**: Reentrant lock for concurrency control
   - Single thread can acquire multiple times
   - Protects schedule queue and message map

### Project Structure

```
sms-scheduler/
├── src/
│   ├── __init__.py
│   ├── scheduler.py          # Core scheduler logic
│   ├── persistence.py        # S3 operations
│   ├── models.py             # Data models
│   ├── config.py             # Configuration
│   ├── main.py               # Entry point
│   ├── api.py                # Flask web server
│   └── templates/
│       └── index.html        # Web UI
├── requirements.txt          # Python dependencies
├── Dockerfile                # Container image
├── docker-compose.yml        # LocalStack setup
└── README.md                 # This file
```

### Concurrency Strategy

**Thread Safety Guarantees:**

- `newMessage()`: Acquires lock → adds to queue → persists to S3
- `wakeup()`: Acquires lock → collects due messages → releases lock → processes
- Processing happens outside locks to avoid blocking
- `RLock` allows same thread to acquire lock recursively

**Why This Works:**

- Lock ensures atomic queue operations
- Heap maintains correct ordering
- Retry times calculated from `created_at` (absolute, not relative)
- State persisted before scheduling next attempt


### Persistence Model (S3 as Source of Truth)

**S3 Layout:**
```
s3://bucket/
  state/
    {messageId}.json     # Active retry state
  success/
    {timestamp}_{messageId}.json     # Successfully sent
  failed/
    {timestamp}_{messageId}.json     # Failed after max retries
```

**State Document Format:**
```json
{
  "message_id": "msg-123",
  "message": {
    "message_id": "msg-123",
    "content": "Test message",
    "metadata": {}
  },
  "attempt_count": 2,
  "next_retry_at": 1700000000.5,
  "status": "PENDING",
  "created_at": 1700000000.0,
  "updated_at": 1700000000.5
}
```

### Complexity Analysis

| Operation | Time | Space | Notes |
|-----------|------|-------|-------|
| `newMessage()` | O(log n) | O(1) | Heap insert dominates |
| `wakeup()` | O(k log n) | O(k) | k = messages due now |
| Persistence (per msg) | O(1) | O(1) | S3 PutObject is constant time |
| State recovery | O(n log n) | O(n) | Load n messages, insert into heap |

**Space:** O(n) for n pending messages in heap + dict

---

## Local RUN instructions (LocalStack)

### Prerequisites

- Python 3.11+
- Docker (for LocalStack)

### Setup
1. Clone repository
```bash
# 1. Clone repository
git clone https://github.com/avrahamgoldberg/sms-retry-project.git
cd messageRetry
```
2. Launch with docker:
```bash
docker-compose up --build
```
3. View in browser:
```aiignore
http://localhost:8080
```
The project contains a DockerFile creating the app image, and a docker-compose file to build the image, as well as pull
and build a LocalStack image to simulate S3 storage. The docker-compose file contains local envs required.


---

## Deploying to EC2 with S3

### Set up resources:
In the AWS console page I created:
 - S3 bucket (sms-retry-scheduler)
 - IAM Role for EC2 (sms-retry-ec2-role)
 - EC2 instance (sms-retry-instance)

Set up EC2 instance with the IAM Role, which is granted S3 access.
To deploy my app to the EC2 instance, I'm using a deploy.sh file.
The deploy file ssh's into the EC2 instance (using my private keypair, stored locally), 
uploads environment variables from local .env file, clones the repo from git and runs it with gunicorn.

View in browser:
```aiignore
http://54.196.246.92:8080
```

---



## Configuration Reference

### Environment Variables

```bash
# AWS Configuration
AWS_ACCESS_KEY_ID=test                  # for local only, deployment uses IAM Role
AWS_SECRET_ACCESS_KEY=test              # for local only, deployment uses IAM Role
AWS_ENDPOINT_URL=http://localhost:4566  # For LocalStack only
AWS_REGION=us-east-1                    # AWS region

# S3 Configuration
S3_BUCKET=sms-retry-scheduler           # S3 bucket name
S3_STATE_PREFIX=state                   # Prefix for active messages
S3_SUCCESS_PREFIX=success               # Prefix for successful sends
S3_FAILED_PREFIX=failed                 # Prefix for failed messages

# Application
API_HOST=0.0.0.0                        # Flask host
API_PORT=8080                           # Flask port
LOG_LEVEL=INFO                          # Logging level
```

### Production vs Development

| Aspect | LocalStack | Real S3 (EC2) |
|--------|------------|---------------|
| **Endpoint** | `http://localhost:4566` | Default (via boto3) |
| **Credentials** | `test`/`test` | IAM role (automatic) |
| **AWS_ENDPOINT_URL** | Set to LocalStack | Not set |
| **Cost** | Free | ~$0.023/GB + requests |
| **Latency** | <1ms | 10-100ms |
| **Best for** | Local testing | Production |


---
### Missing from project:
I didn't implement the ability to configure the S3 paths from the web UI, in part for lack of time but
also because it seems a strange feature. The S3 paths are provided as environment variables, and I don't see why
we would want them to change in runtime. 

Had I implemented the feature, I would have added a file in the bucket which
stores the path names (its key would inevitably be an env), so that the app can know what paths to use. Whenever they are changed the existing paths
would be copied into the new paths and deleted, and the new path names stored again in the paths file.

I hope I understood this correctly.