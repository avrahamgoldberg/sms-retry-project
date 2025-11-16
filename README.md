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
The project contains a DockerFile creating the app image, and a docker-compose file to build the image, as well as pull
and build a LocalStack image to simulate S3 storage. The docker-compose file contains local envs required.


---

## Deploying to EC2 with S3

### Set up resources:
In the AWS console page create:
 - S3 bucket
 - IAM Role for EC2 

### Step 4: Launch EC2 Instance

```bash
# 1. Create security group
aws ec2 create-security-group \
  --group-name sms-scheduler-sg \
  --description "SMS Scheduler security group"

SG_ID=$(aws ec2 describe-security-groups \
  --group-names sms-scheduler-sg \
  --query 'SecurityGroups[0].GroupId' \
  --output text)

# 2. Allow inbound traffic
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 8080 \
  --cidr 0.0.0.0/0

aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0

# 3. Create user data script
cat > user-data.sh <<'EOF'
#!/bin/bash
set -e

# Install Docker
yum update -y
yum install -y docker
service docker start
usermod -a -G docker ec2-user
systemctl enable docker

# Pull and run application
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com

docker pull ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/sms-scheduler:latest

docker run -d \
  --name sms-scheduler \
  --restart unless-stopped \
  -p 8080:8080 \
  -e AWS_REGION=us-east-1 \
  -e S3_BUCKET=sms-scheduler-prod \
  -e S3_STATE_PREFIX=state \
  -e S3_SUCCESS_PREFIX=success \
  -e S3_FAILED_PREFIX=failed \
  ${ACCOUNT_ID}.dkr.ecr.us-east-1.amazonaws.com/sms-scheduler:latest

echo "SMS Scheduler started successfully"
EOF

# 4. Launch instance
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.small \
  --key-name your-key-pair \
  --security-group-ids $SG_ID \
  --iam-instance-profile Name=sms-scheduler-ec2-profile \
  --user-data file://user-data.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=sms-scheduler}]'
```

### Step 6: Manual Deployment (SSH Method)

If you prefer to SSH and set up manually:

```bash
# 1. SSH into EC2
ssh -i your-key.pem ec2-user@$PUBLIC_IP

# 2. Install Docker
sudo yum update -y
sudo yum install -y docker git
sudo service docker start
sudo usermod -a -G docker ec2-user

# 3. Logout and login (for docker group)
exit
ssh -i your-key.pem ec2-user@$PUBLIC_IP

# 4. Clone repository
git clone <your-repo-url>
cd sms-scheduler

# 5. Build and run
docker build -t sms-scheduler:latest .

docker run -d \
  --name sms-scheduler \
  --restart unless-stopped \
  -p 8080:8080 \
  -e AWS_REGION=us-east-1 \
  -e S3_BUCKET=sms-scheduler-prod \
  -e S3_STATE_PREFIX=state \
  -e S3_SUCCESS_PREFIX=success \
  -e S3_FAILED_PREFIX=failed \
  sms-scheduler:latest

# 6. Check logs
docker logs -f sms-scheduler
```

---

## Testing

### Send Test Messages

```bash
# Single message
curl -X POST http://localhost:8080/api/send \
  -H "Content-Type: application/json" \
  -d '{"content": "Test message"}'

# Bulk messages
curl -X POST http://localhost:8080/api/send-bulk \
  -H "Content-Type: application/json" \
  -d '{"content": "Load test", "count": 100}'

# Check stats
curl http://localhost:8080/api/stats | python -m json.tool
```

### Verify S3 Persistence

```bash
# LocalStack
aws --endpoint-url=http://localhost:4566 s3 ls s3://sms-retry-scheduler/ --recursive

# Real S3
aws s3 ls s3://sms-scheduler-prod/ --recursive

# View a message state
aws s3 cp s3://sms-scheduler-prod/state/some-message-id.json - | python -m json.tool
```

---

## Configuration Reference

### Environment Variables

```bash
# AWS Configuration
AWS_REGION=us-east-1                    # AWS region
AWS_ACCESS_KEY_ID=...                   # (Optional) AWS credentials
AWS_SECRET_ACCESS_KEY=...               # (Optional) AWS credentials
AWS_ENDPOINT_URL=http://localhost:4566  # For LocalStack only

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

## Troubleshooting

### Issue: "NoSuchBucket" Error

```bash
# For LocalStack
aws --endpoint-url=http://localhost:4566 s3 mb s3://sms-retry-scheduler

# For real S3
aws s3 mb s3://your-bucket-name --region us-east-1
```

### Issue: "Access Denied" on EC2

```bash
# Check IAM role is attached
aws ec2 describe-instances --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].IamInstanceProfile'

# Test S3 access from EC2
ssh -i your-key.pem ec2-user@$PUBLIC_IP
aws s3 ls s3://sms-scheduler-prod/
```

### Issue: Application Not Starting

```bash
# Check Docker logs
docker logs sms-scheduler

# Check if container is running
docker ps

# Restart container
docker restart sms-scheduler
```

### Issue: LocalStack Not Working

```bash
# Check LocalStack is running
docker ps | grep localstack

# Check LocalStack health
curl http://localhost:4566/_localstack/health

# Restart LocalStack
docker-compose restart localstack

# View LocalStack logs
docker-compose logs -f localstack
```

---

## Known Trade-offs

### ✅ Prioritized

1. **Correctness**: Exact retry timings maintained
2. **Durability**: S3 persistence survives restarts
3. **Concurrency**: Thread-safe with RLock

### ⚠️ Limitations

1. **S3 Latency**: 50-100ms per write limits throughput to ~10-20 msg/sec
   - **Solution**: Use DynamoDB for higher throughput

2. **Single-Instance**: No distributed coordination
   - **Solution**: Add DynamoDB conditional writes for multi-instance

3. **No Deduplication**: Same message ID can be added twice
   - **Mitigation**: Caller ensures unique IDs

4. **Python GIL**: Threading limited by Global Interpreter Lock
   - **Impact**: Minimal for I/O-bound workload (S3, network)
   - **Solution**: Use multiprocessing or async/await if needed

---

## Next Steps

- Read the full architecture explanation above
- Run locally with LocalStack
- Deploy to EC2 with real S3
- Review `scheduler.py` for implementation details
- Customize retry schedule in `models.py`

## License

MIT License