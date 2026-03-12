# AWS Security Hub Cost Estimation Tool

**One-time, read-only data collection tool** for estimating AWS Security Hub costs across your organization.

## What This Tool Does

This tool **runs once** to collect resource metrics from your AWS accounts and generates a CSV report for cost estimation. It:

- ✅ **Read-only operations** - Makes no changes to your environment
- ✅ **One-time execution** - Collects data snapshot, then stops
- ✅ **No persistent resources** - Lambda runs once via CloudFormation, results saved to S3
- ✅ **Works with or without Security Hub enabled** - Collects resource data regardless of whether Security Hub is currently active

**Use Case:** Estimate monthly Security Hub costs based on your current resource usage — whether you're evaluating Security Hub before enabling it, or reviewing costs for an existing deployment.

## What This Collects

| Metric | Source | Used For |
|--------|--------|----------|
| EC2 instance hours/month | Cost Explorer (management account, last month) | Security Hub EC2 pricing |
| ECR images pushed (last 7 days) | Inspector if enabled, otherwise ECR API | Security Hub ECR scanning pricing |
| Lambda functions (active last 90 days) | Inspector if enabled, otherwise Lambda API | Security Hub Lambda scanning pricing |
| IAM users & roles | IAM API | Security Hub IAM analysis pricing |

## Deployment Overview

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Deploy IAM Role to Management Account                  │
│                                                                 │
│  Management Account (SecurityHubCostEstimatorRole)             │
│  └──> Used for org-wide EC2 hours via Cost Explorer            │
│                                                                 │
│  ⚠️  Cost Explorer data is only available here                 │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Deploy IAM Role to Member Accounts (via StackSets)     │
│                                                                 │
│       ├──> Member Account 1 (SecurityHubCostEstimatorRole)     │
│       ├──> Member Account 2 (SecurityHubCostEstimatorRole)     │
│       ├──> Member Account 3 (SecurityHubCostEstimatorRole)     │
│       └──> ... (all member accounts)                           │
│                                                                 │
│  ⚠️  Lambda CANNOT run without this role in each account       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Deploy Lambda Collector (in Audit/Security Account)    │
│                                                                 │
│  Audit/Security Account                                         │
│       │                                                         │
│       └──> Lambda Function (runs once automatically)           │
│            │                                                    │
│            ├──> Assumes role in Management Account             │
│            │    └──> Gets org-wide EC2 hours (Cost Explorer)   │
│            ├──> Assumes role in Member Account 1               │
│            ├──> Assumes role in Member Account 2               │
│            └──> Saves results to S3                            │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Option 1: CloudFormation Deployment (Recommended)

**This is the recommended approach** - deploys a Lambda function that runs once automatically.

> **⚠️ IMPORTANT:** You must deploy the read-only IAM role to **ALL accounts** in your organization BEFORE deploying the Lambda collector. The Lambda cannot collect data without this role in each account.

#### Prerequisites

Before starting, you need:
1. **Management account access** (or CloudFormation StackSets delegated admin) to deploy roles organization-wide
2. **Audit/Security account access** where you'll run the Lambda collector
3. **Account ID** of the audit/security account where Lambda will run

#### Step 1: Deploy Read-Only Role to Management Account

**Deploy the IAM role to your management (payer) account first.** The Lambda uses this role to retrieve org-wide EC2 hours from Cost Explorer, which is only available in the management account.

From your **management account**:

```bash
aws cloudformation deploy \
  --template-file member-account-role.yaml \
  --stack-name security-hub-cost-estimator-role \
  --parameter-overrides CollectorAccountId=YOUR_COLLECTOR_ACCOUNT_ID \
  --capabilities CAPABILITY_NAMED_IAM
```

#### Step 2: Deploy Read-Only Role to All Member Accounts

**Deploy the IAM role to every member account via StackSets.** The Lambda needs this role to collect ECR, Lambda, and IAM data from each account.

> **Note:** StackSets don't deploy to the management account — that's why Step 1 is required.

**Option A: Deploy via CloudFormation StackSets (Recommended)**

From your management account or CloudFormation delegated admin:

```bash
# Clone the repository
git clone <repository-url>
cd aws-security-hub-cost-estimator

# Deploy via StackSets (run from management account or delegated admin)
aws cloudformation create-stack-set \
  --template-body file://member-account-role.yaml \
  --stack-set-name security-hub-cost-estimator-roles \
  --permission-model SERVICE_MANAGED \
  --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters ParameterKey=CollectorAccountId,ParameterValue=YOUR_COLLECTOR_ACCOUNT_ID \
  --call-as SELF

# Create stack instances for all accounts in your organization
aws cloudformation create-stack-instances \
  --stack-set-name security-hub-cost-estimator-roles \
  --deployment-targets OrganizationalUnitIds='["YOUR_ROOT_OU_ID"]' \
  --regions '["us-east-1"]' \
  --operation-preferences FailureTolerancePercentage=100,MaxConcurrentPercentage=100
```

**Option B: Deploy via AWS Console**

1. Sign in to your **management account** or CloudFormation delegated admin account
2. Navigate to **CloudFormation** → **StackSets**
3. Click **Create StackSet**
4. Choose **Template is ready** → **Upload a template file**
5. Upload `member-account-role.yaml`
6. Click **Next**
7. Enter StackSet name: `security-hub-cost-estimator-roles`
8. Set parameter **CollectorAccountId** to your audit/security account ID
9. Click **Next**
10. Under **Permissions**, select **Service-managed permissions**
11. Enable **Automatic deployment**
12. Click **Next**
13. Under **Deployment targets**, select **Deploy to organization**
14. Choose your root OU or specific OUs
15. Select region: **us-east-1**
16. Set **Maximum concurrent accounts**: 100%
17. Set **Failure tolerance**: 100%
18. Click **Next** → **Submit**

#### Step 3: Deploy Lambda Collector

Deploy the Lambda function in your audit/security tooling account:

**Option A: Deploy via AWS CLI**

```bash
# Deploy the stack
aws cloudformation deploy \
  --template-file security-hub-cost-estimator.yaml \
  --stack-name security-hub-cost-estimator \
  --parameter-overrides \
    CrossAccountRoleName=SecurityHubCostEstimatorRole \
    TargetRegion=us-east-1 \
    ManagementAccountId=YOUR_MANAGEMENT_ACCOUNT_ID \
  --capabilities CAPABILITY_IAM
```

**Option B: Deploy via AWS Console**

1. Sign in to your **audit/security account**
2. Navigate to **CloudFormation** → **Stacks**
3. Click **Create stack** → **With new resources (standard)**
4. Choose **Template is ready** → **Upload a template file**
5. Upload `security-hub-cost-estimator.yaml`
6. Click **Next**
7. Enter Stack name: `security-hub-cost-estimator`
8. Set parameters:
   - **CrossAccountRoleName**: `SecurityHubCostEstimatorRole`
   - **TargetRegion**: `us-east-1` (or your preferred region)
   - **ManagementAccountId**: Your management (payer) account ID
   - **AccountIds**: Leave empty to auto-discover via Organizations
9. Click **Next**
10. Scroll to bottom, check **I acknowledge that AWS CloudFormation might create IAM resources**
11. Click **Submit**

The Lambda function runs automatically once when the stack is created. Results are saved to the S3 bucket created by the stack.

#### Step 3: Retrieve Results

```bash
# Get the bucket name from stack outputs
BUCKET=$(aws cloudformation describe-stacks \
  --stack-name security-hub-cost-estimator \
  --query 'Stacks[0].Outputs[?OutputKey==`ResultsBucket`].OutputValue' \
  --output text)

# Download the results
aws s3 ls s3://$BUCKET/
aws s3 cp s3://$BUCKET/security_hub_cost_data_YYYYMMDD_HHMMSS.csv ./
```

### Option 2: Python Scripts (Manual)

Use these scripts if you prefer to run the collection manually or need more control.

**Where to Run:** Run from AWS CloudShell, your local machine, or an EC2 instance with appropriate AWS credentials.

#### Prerequisites

```bash
pip install boto3
```

#### Run the Script

**Single Account:**
```bash
python3 collect_security_hub_data.py
```

**Multiple Accounts:**
```bash
python3 collect_security_hub_data_multi_account.py --role-name SecurityHubCostEstimatorRole --management-account YOUR_MANAGEMENT_ACCOUNT_ID
```

## Output

Creates a CSV file: `security_hub_data_YYYYMMDD_HHMMSS.csv`

Example:
```csv
Account ID,Region,ECR Images (Last 7 Days),Lambda Functions (Active 90 Days),IAM Users,IAM Roles,Data Source ECR,Data Source Lambda
123456789012,us-east-1,42,30,12,85,Inspector,Inspector
234567890123,us-east-1,10,15,5,45,ECR API,Lambda API

Org-Wide EC2 Monthly Hours (from Cost Explorer),18000
Avg EC2 Instances (Hours/720),25.0
```

Use this data with the [Security Hub Pricing Calculator](https://aws.amazon.com/security-hub/pricing/) or your internal pricing tool.

## Required IAM Permissions

**The only requirement is a read-only IAM role** in each account. When deployed with the provided IAM policies, the tool is designed to make no changes to your environment.

### Member Account Role (Read-Only)

Deploy `member-account-role.yaml` to each account. This creates a role designed with least-privilege principles, granting only these read-only permissions:

| Service | Permissions | Purpose |
|---------|-------------|---------|
| **Cost Explorer** | `ce:GetCostAndUsage` | Get EC2 instance hours from last month for Security Hub EC2 pricing |
| **ECR** | `ecr:DescribeRepositories`<br>`ecr:DescribeImages` | Count container images pushed in last 7 days for Security Hub ECR scanning pricing |
| **Lambda** | `lambda:ListFunctions` | Count Lambda functions active in last 90 days for Security Hub Lambda scanning pricing |
| **IAM** | `iam:ListUsers`<br>`iam:ListRoles` | Count IAM resources for Security Hub IAM analysis pricing |
| **Amazon Inspector** | `inspector2:ListCoverage` | Get ECR and Lambda data from Inspector if enabled (preferred source) |

<details>
<summary>View full IAM policy JSON</summary>

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostExplorerReadOnly",
      "Effect": "Allow",
      "Action": ["ce:GetCostAndUsage"],
      "Resource": "*"
    },
    {
      "Sid": "ECRReadOnly",
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeRepositories",
        "ecr:DescribeImages"
      ],
      "Resource": "*"
    },
    {
      "Sid": "LambdaReadOnly",
      "Effect": "Allow",
      "Action": ["lambda:ListFunctions"],
      "Resource": "*"
    },
    {
      "Sid": "IAMReadOnly",
      "Effect": "Allow",
      "Action": [
        "iam:ListUsers",
        "iam:ListRoles"
      ],
      "Resource": "*"
    },
    {
      "Sid": "InspectorReadOnly",
      "Effect": "Allow",
      "Action": ["inspector2:ListCoverage"],
      "Resource": "*",
      "Comment": "Amazon Inspector - resource-level permissions not supported"
    }
  ]
}
```

The role trust policy restricts access to **only** the Lambda execution role in your collector account:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "AWS": "arn:aws:iam::COLLECTOR_ACCOUNT_ID:root"
    },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringLike": {
        "aws:PrincipalArn": "arn:aws:iam::COLLECTOR_ACCOUNT_ID:role/*LambdaExecutionRole*"
      }
    }
  }]
}
```

</details>

### Collector Account Permissions

The Lambda function in your collector account needs:
- `sts:AssumeRole` - To assume the read-only role in member accounts
- `organizations:ListAccounts` - To discover accounts (if not providing explicit list)
- `s3:PutObject` - To save results to the S3 bucket

These are automatically configured by `security-hub-cost-estimator.yaml`.

## Usage Examples

### Single Account - Different Region
```bash
python3 collect_security_hub_data.py --region us-west-2
```

### Single Account - Specific AWS Profile
```bash
python3 collect_security_hub_data.py --profile production
```

### Multiple Accounts - Auto-discover via Organizations
```bash
python3 collect_security_hub_data_multi_account.py \
  --role-name SecurityHubDataCollectionRole \
  --management-account YOUR_MANAGEMENT_ACCOUNT_ID
```

### Multiple Accounts - Specific Account List
```bash
python3 collect_security_hub_data_multi_account.py \
  --role-name SecurityHubDataCollectionRole \
  --management-account YOUR_MANAGEMENT_ACCOUNT_ID \
  --accounts 111111111111,222222222222,333333333333
```

### Multiple Accounts - Different Region
```bash
python3 collect_security_hub_data_multi_account.py \
  --role-name SecurityHubDataCollectionRole \
  --management-account YOUR_MANAGEMENT_ACCOUNT_ID \
  --region eu-west-1
```

## Multi-Account Setup

For multi-account collection, the read-only IAM role must be deployed to each member account. Use the CloudFormation StackSets approach in the Quick Start section above, or deploy manually:

### Deploy Role to Member Accounts

Use the provided `member-account-role.yaml` template:

```bash
aws cloudformation deploy \
  --template-file member-account-role.yaml \
  --stack-name security-hub-cost-estimator-role \
  --parameter-overrides CollectorAccountId=MANAGEMENT_ACCOUNT_ID \
  --capabilities CAPABILITY_NAMED_IAM
```

This creates a role with:
- **Read-only permissions** for Cost Explorer, ECR, Lambda, IAM, and Amazon Inspector
- **Trust policy** that restricts access to only the Lambda execution role in your collector account
- **No write permissions** - cannot modify any resources

## Notes

- **Read-only design**: Scripts are designed to make no changes to your AWS environment when used with the provided IAM policies
- **EC2 hours**: Retrieved from Cost Explorer in the management (payer) account for the previous calendar month (org-wide total)
- **ECR images**: Images pushed in the last 7 days, sourced from Inspector if enabled, otherwise ECR API
- **Lambda functions**: Functions updated or invoked in the last 90 days, sourced from Inspector if enabled, otherwise Lambda API
- **Multi-account**: Processes 5 accounts in parallel (configurable with `--max-workers`)
- **One-time execution**: Lambda runs once when CloudFormation stack is created

## License

MIT License - See LICENSE file for details
