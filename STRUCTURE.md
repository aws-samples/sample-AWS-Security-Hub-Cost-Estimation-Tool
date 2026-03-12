# Repository Structure

## Core Files

### CloudFormation Templates
- **`security-hub-cost-estimator.yaml`** - Main template that deploys Lambda function for one-time data collection
- **`member-account-role.yaml`** - Read-only IAM role template to deploy in each member account

### Python Scripts (Optional Manual Use)
- **`collect_security_hub_data.py`** - Single account data collection script
- **`collect_security_hub_data_multi_account.py`** - Multi-account data collection script

### Documentation
- **`README.md`** - Complete usage guide with deployment instructions
- **`LICENSE`** - MIT License
- **`CONTRIBUTING.md`** - Contribution guidelines
- **`requirements.txt`** - Python dependencies (boto3)

### Configuration
- **`.gitignore`** - Git ignore rules for AWS credentials, output files, etc.

## Deployment Options

### Option 1: CloudFormation (Recommended)
1. Deploy `member-account-role.yaml` to all accounts via StackSets
2. Deploy `security-hub-cost-estimator.yaml` to collector account
3. Lambda runs automatically once
4. Download CSV from S3

### Option 2: Python Scripts (Manual)
1. Deploy `member-account-role.yaml` to all accounts
2. Run Python script from CloudShell or local machine
3. CSV saved locally

## Security Design Features

- ✅ Read-only IAM permissions
- ✅ Least-privilege role design
- ✅ Restricted trust policy (Lambda execution role only)
- ✅ One-time execution (no persistent resources)
- ✅ Encrypted S3 storage
- ✅ No write permissions

## Tested Scenarios

- ✅ Single account deployment
- ✅ Multi-account Organizations deployment via StackSets
- ✅ Cross-account role assumption
- ✅ Parallel data collection (5 workers)
- ✅ Error handling for accounts without role
- ✅ Organizations API auto-discovery

## Output

CSV file with columns:
- Account ID
- Region
- EC2 Instances
- EC2 Monthly Hours
- ECR Repositories
- ECR Images
- Lambda Functions
- IAM Users
- IAM Roles
- Lambda Scanned
- Error (if any)
