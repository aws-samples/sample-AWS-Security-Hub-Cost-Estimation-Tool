#!/usr/bin/env python3
"""
AWS Security Hub Cost Estimation - Single Account Data Collection

Collects resource usage data for Security Hub pricing estimation.
"""

import boto3
import csv
from datetime import datetime, timedelta, timezone
import argparse


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
        print(f"Cost Explorer error: {e}")
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
                # Lambda LastModified format: 2024-01-15T10:30:00.000+0000
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
        print(f"ECR access error: {e}")
    return count


def collect_data(session, region):
    """Collect all required metrics"""
    ecr = session.client('ecr', region_name=region)
    lambda_client = session.client('lambda', region_name=region)
    iam = session.client('iam')
    inspector = session.client('inspector2', region_name=region)
    sts = session.client('sts')
    
    account_id = sts.get_caller_identity()['Account']
    
    # EC2 - use Cost Explorer for last month's hours
    ec2_hours = get_ec2_hours_from_cost_explorer(session, region)
    
    # ECR - try Inspector first, fall back to ECR API (last 7 days)
    inspector_enabled = False
    inspector_ecr, ecr_images = get_recent_ecr_images_from_inspector(inspector)
    if inspector_ecr:
        inspector_enabled = True
    else:
        ecr_images = get_recent_ecr_images_from_api(ecr)
    
    # Lambda - try Inspector first, fall back to Lambda API (last 90 days)
    inspector_lambda, lambda_count = get_active_lambda_from_inspector(inspector)
    if inspector_lambda:
        inspector_enabled = True
    else:
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
        'ec2_monthly_hours': ec2_hours,
        'ecr_images_recent': ecr_images,
        'lambda_functions_active': lambda_count,
        'iam_users': len(users),
        'iam_roles': len(roles),
        'data_source_ecr': 'Inspector' if inspector_ecr else 'ECR API',
        'data_source_lambda': 'Inspector' if inspector_lambda else 'Lambda API',
    }


def main():
    parser = argparse.ArgumentParser(description='Collect AWS Security Hub cost estimation data')
    parser.add_argument('--region', default='us-east-1', help='AWS region (default: us-east-1)')
    parser.add_argument('--profile', help='AWS profile name')
    args = parser.parse_args()
    
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    
    print(f"Collecting data from region {args.region}...")
    data = collect_data(session, args.region)
    
    # Save CSV
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'security_hub_data_{timestamp}.csv'
    
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Account ID', 'Region', 'EC2 Monthly Hours', 'Avg EC2 Instances (Hours/720)',
            'ECR Images (Last 7 Days)', 'Lambda Functions (Active 90 Days)',
            'IAM Users', 'IAM Roles',
            'Data Source ECR', 'Data Source Lambda'
        ])
        writer.writerow([
            data['account_id'], data['region'],
            data['ec2_monthly_hours'], round(data['ec2_monthly_hours'] / 720, 2),
            data['ecr_images_recent'],
            data['lambda_functions_active'], data['iam_users'], data['iam_roles'],
            data['data_source_ecr'], data['data_source_lambda']
        ])
    
    print(f"\n{'='*60}")
    print(f"Account: {data['account_id']} | Region: {data['region']}")
    print(f"{'='*60}")
    print(f"EC2 Monthly Hours (Cost Explorer): {data['ec2_monthly_hours']:,.0f}")
    print(f"Avg EC2 Instances (Hours/720): {data['ec2_monthly_hours'] / 720:,.2f}")
    print(f"ECR Images (last 7 days, via {data['data_source_ecr']}): {data['ecr_images_recent']}")
    print(f"Lambda Functions (active 90 days, via {data['data_source_lambda']}): {data['lambda_functions_active']}")
    print(f"IAM: {data['iam_users']} users, {data['iam_roles']} roles")
    print(f"{'='*60}")
    print(f"\nResults saved to: {filename}")


if __name__ == '__main__':
    main()
