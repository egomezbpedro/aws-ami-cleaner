# EC2 Image Search Tool

A Python utility to search for EC2 images (AMIs) in a specific AWS region by keyword.

## Usage

```bash
# Search for an image name or keyword in a region
python3 search_images.py "ubuntu" --region us-west-2
```

### Deletion Operations

#### Dry run (recommended first step)

```bash
# See what would be deleted without actually deleting
python3 search_images.py "test" --region us-west-2 --dry-run
```

#### Delete with confirmation prompt

```bash
# Interactive deletion with confirmation
python3 search_images.py "test" --region us-west-2 --delete --older-than 30d
```

#### Delete with custom queue size

```bash
# Process 5 deletions concurrently
python3 search_images.py "test" --region us-west-2 --delete --queue-size 5
```

#### Skip confirmation (for automation)

```bash
# Delete without confirmation prompt
python3 search_images.py "test" --region us-west-2 --delete --confirm
```

#### Search for custom images

```bash
python3 search_images.py "my-app" --region us-west-2 --format json
```

## Output Fields

- **Region**: AWS region where the image is located
- **ImageId**: AMI ID
- **Name**: Image name
- **Description**: Image description
- **CreationDate**: When the image was created
- **Architecture**: CPU architecture (x86_64, arm64, etc.)
- **Platform**: Operating system platform (Linux, Windows)
- **State**: Image state (available, pending, failed)