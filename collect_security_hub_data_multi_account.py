#!/usr/bin/env python3
"""
AWS Security Hub Cost Estimation - Multi-Account Data Collection

Collects data across multiple AWS accounts using cross-account roles.
"""

import boto3
import csv
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse


def assume_role(account_id, role_name):
    """Assume role in target account"""
    sts = boto3.client('sts')
    role_arn = f'arn:aws:iam::{account_id}:role/{role_name}'
    
    try:
        response = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName='SecurityHubCostEstimator'
        )
        return boto3.Session(
            aws_access_key_id=response['Credentials']['AccessKeyId'],
            aws_secret_access_key=response['Credentials']['SecretAccessKey'],
            aws_session_token=response['Credentials']['SessionToken']
        )
    except Exception as e:
        print(f"  ERROR: Failed to assume role in {account_id}: {e}")
        return None


def get_ec2_hours_from_cost_explorer(session, region):
    """Get EC2 instance hours from Cost Explorer for last month"""
    ce = session.client('ce', region_name=region)
    now = datetime.now(timezone.utc)
    start = (now.replace(day=1) - timedelta(days=1)).replace(day=1).strftime('%Y-%m-%d')
    end = now.replace(day=1).strftime('%Y-%m-%d')
    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={'Start': start, 'End': end},
            Granularity='MONTHLY',
            Metrics=['UsageQuantity'],
            Filter={'Dimensions': {'Key': 'SERVICE', 'Values': ['Amazon Elastic Compute Cloud - Compute']}}
        )
        for result in resp.get('ResultsByTime', []):
            return float(result['Total']['UsageQuantity']['Amount'])
    except Exception as e:
        print(f"  Cost Explorer error in account: {e}")
    return 0


def get_active_lambda_from_inspector(inspector):
    """Try to get Lambda functions tracked by Inspector"""
    try:
        funcs = set()
        paginator = inspector.get_paginator('list_coverage')
        for page in paginator.paginate(
            filterCriteria={'resourceType': [{'comparison': 'EQUALS', 'value': 'AWS_LAMBDA_FUNCTION'}]}
        ):
            for item in page.get('coveredResources', []):
                funcs.add(item.get('resourceId', ''))
        return True, len(funcs)
    except Exception:
        return False, 0


def get_active_lambda_from_api(lambda_client):
    """Get Lambda functions updated/invoked in last 90 days"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    count = 0
    paginator = lambda_client.get_paginator('list_functions')
    for page in paginator.paginate():
        for fn in page['Functions']:
            last_modified = fn.get('LastModified', '')
            if last_modified:
                mod_time = datetime.fromisoformat(last_modified.replace('+0000', '+00:00'))
                if mod_time >= cutoff:
                    count += 1
    return count


def get_recent_ecr_images_from_inspector(inspector):
    """Try to get ECR image count from Inspector"""
    try:
        count = 0
        paginator = inspector.get_paginator('list_coverage')
        for page in paginator.paginate(
            filterCriteria={'resourceType': [{'comparison': 'EQUALS', 'value': 'AWS_ECR_CONTAINER_IMAGE'}]}
        ):
            count += len(page.get('coveredResources', []))
        return True, count
    except Exception:
        return False, 0


def get_recent_ecr_images_from_api(ecr):
    """Get ECR images pushed in last 7 days"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    count = 0
    try:
        repos = ecr.describe_repositories()
        for repo in repos.get('repositories', []):
            paginator = ecr.get_paginator('describe_images')
            for page in paginator.paginate(repositoryName=repo['repositoryName']):
                for img in page.get('imageDetails', []):
                    if img.get('imagePushedAt') and img['imagePushedAt'] >= cutoff:
                        count += 1
    except Exception as e:
        print(f"  ECR access error: {e}")
    return count


def collect_account_data(account_id, role_name, region):
    """Collect data for a single account"""
    print(f"Processing {account_id}...")
    
    session = assume_role(account_id, role_name)
    if not session:
        return {'account_id': account_id, 'region': region, 'error': 'Failed to assume role'}
    
    try:
        ecr = session.client('ecr', region_name=region)
        lambda_client = session.client('lambda', region_name=region)
        iam = session.client('iam')
        inspector = session.client('inspector2', region_name=region)
        
        # ECR - try Inspector first, fall back to ECR API (last 7 days)
        inspector_ecr, ecr_images = get_recent_ecr_images_from_inspector(inspector)
        if not inspector_ecr:
            ecr_images = get_recent_ecr_images_from_api(ecr)
        
        # Lambda - try Inspector first, fall back to Lambda API (last 90 days)
        inspector_lambda, lambda_count = get_active_lambda_from_inspector(inspector)
        if not inspector_lambda:
            lambda_count = get_active_lambda_from_api(lambda_client)
        
        # IAM
        users = []
        user_paginator = iam.get_paginator('list_users')
        for page in user_paginator.paginate():
            users.extend(page['Users'])
        
        roles = []
        role_paginator = iam.get_paginator('list_roles')
        for page in role_paginator.paginate():
            roles.extend(page['Roles'])
        
        return {
            'account_id': account_id,
            'region': region,
            'ecr_images_recent': ecr_images,
            'lambda_functions_active': lambda_count,
            'iam_users': len(users),
            'iam_roles': len(roles),
            'data_source_ecr': 'Inspector' if inspector_ecr else 'ECR API',
            'data_source_lambda': 'Inspector' if inspector_lambda else 'Lambda API',
        }
    except Exception as e:
        return {'account_id': account_id, 'region': region, 'error': str(e)}


def get_org_accounts():
    """Get all active accounts from AWS Organizations"""
    org = boto3.client('organizations')
    accounts = []
    paginator = org.get_paginator('list_accounts')
    for page in paginator.paginate():
        accounts.extend([a for a in page['Accounts'] if a['Status'] == 'ACTIVE'])
    return [a['Id'] for a in accounts]


def main():
    parser = argparse.ArgumentParser(description='Collect Security Hub data across multiple accounts')
    parser.add_argument('--role-name', required=True, help='IAM role name in member accounts')
    parser.add_argument('--management-account', required=True, help='Management (payer) account ID for Cost Explorer data')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--accounts', help='Comma-separated account IDs (or use Organizations)')
    parser.add_argument('--max-workers', type=int, default=5, help='Parallel workers (default: 5)')
    args = parser.parse_args()
    
    # Get accounts
    if args.accounts:
        account_ids = [a.strip() for a in args.accounts.split(',')]
        import re
        for acc_id in account_ids:
            if not re.match(r'^\d{12}$', acc_id):
                raise ValueError(f"Invalid account ID format: {acc_id}. Must be 12 digits.")
    else:
        print("Fetching accounts from AWS Organizations...")
        account_ids = get_org_accounts()
    
    print(f"\nCollecting data from {len(account_ids)} accounts...\n")
    
    # Exclude management account from member collection
    account_ids = [a for a in account_ids if a != args.management_account]
    
    # Get org-wide EC2 hours from management account Cost Explorer
    ec2_hours = 0
    mgmt_session = assume_role(args.management_account, args.role_name)
    if mgmt_session:
        ec2_hours = get_ec2_hours_from_cost_explorer(mgmt_session, args.region)
        print(f"Org-wide EC2 hours (from management account): {ec2_hours:,.0f}\n")
    else:
        print("WARNING: Could not assume role in management account for Cost Explorer data\n")
    
    # Collect member account data in parallel
    results = []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(collect_account_data, acc, args.role_name, args.region): acc 
                  for acc in account_ids}
        for future in as_completed(futures):
            results.append(future.result())
    
    # Save CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'security_hub_data_multi_{timestamp}.csv'
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Account ID', 'Region',
            'ECR Images (Last 7 Days)', 'Lambda Functions (Active 90 Days)',
            'IAM Users', 'IAM Roles',
            'Data Source ECR', 'Data Source Lambda', 'Error'
        ])
        for d in results:
            writer.writerow([
                d.get('account_id', ''), d.get('region', ''),
                d.get('ecr_images_recent', 0),
                d.get('lambda_functions_active', 0), d.get('iam_users', 0),
                d.get('iam_roles', 0),
                d.get('data_source_ecr', ''), d.get('data_source_lambda', ''),
                d.get('error', '')
            ])
        writer.writerow([])
        writer.writerow([f'Org-Wide EC2 Monthly Hours (from Cost Explorer)', ec2_hours])
        writer.writerow([f'Avg EC2 Instances (Hours/720)', round(ec2_hours / 720, 2)])
    
    # Summary
    total_lambda = sum(d.get('lambda_functions_active', 0) for d in results)
    total_ecr = sum(d.get('ecr_images_recent', 0) for d in results)
    
    print(f"\n{'='*60}")
    print(f"Accounts: {len(results)} | Org-Wide EC2 Hours (Cost Explorer): {ec2_hours:,.0f}")
    print(f"Total Active Lambda (90 days): {total_lambda:,} | Total ECR Images (7 days): {total_ecr:,}")
    print(f"{'='*60}")
    print(f"\nResults saved to: {filename}")


if __name__ == '__main__':
    main()
