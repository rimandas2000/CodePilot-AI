# Python Basics

## Variables
Python variables are created by assignment.

```python
name = "Riman"
age = 20
```

Python is dynamically typed, so a variable can refer to values of different types at different times.

## Lists
A list stores multiple values.

```python
numbers = [10, 20, 30]
print(numbers[0])
```

Indexes start at zero. Accessing an index outside the list raises IndexError.

## Functions
Functions are defined using `def`.

```python
def add(a, b):
    return a + b
```

## Loops
A for loop iterates over an iterable.

```python
for number in numbers:
    print(number)
```

A while loop continues while its condition is true.

## Exceptions
Use try/except to handle expected runtime errors.

```python
try:
    value = int(input("Enter a number: "))
except ValueError:
    print("Please enter a valid integer.")
```

## Dictionaries
Dictionaries store key-value pairs.

```python
student = {"name": "Riman", "marks": 90}
print(student["name"])
```

## Common beginner bugs
- Using an invalid list index causes IndexError.
- Converting non-numeric input with int() can cause ValueError.
- Using an undefined variable causes NameError.
- Mixing incompatible types can cause TypeError.
