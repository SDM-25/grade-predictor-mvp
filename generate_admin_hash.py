"""
Helper script to generate bcrypt password hash for admin login.
Run this script to create a secure password hash for ADMIN_PASSWORD_HASH.
"""
import bcrypt
import getpass

def generate_hash():
    print("=" * 50)
    print("Admin Password Hash Generator")
    print("=" * 50)
    print()

    password = getpass.getpass("Enter admin password: ")
    password_confirm = getpass.getpass("Confirm password: ")

    if password != password_confirm:
        print("\n❌ Passwords don't match. Please try again.")
        return

    if len(password) < 8:
        print("\n⚠️  Warning: Password is less than 8 characters. Consider using a stronger password.")

    # Generate bcrypt hash
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    hashed_str = hashed.decode('utf-8')

    print("\n✅ Hash generated successfully!")
    print("\n" + "=" * 50)
    print("Add this to your Streamlit Cloud secrets:")
    print("=" * 50)
    print(f'\nADMIN_PASSWORD_HASH = "{hashed_str}"')
    print("\n" + "=" * 50)

if __name__ == "__main__":
    try:
        generate_hash()
    except KeyboardInterrupt:
        print("\n\nOperation cancelled.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
