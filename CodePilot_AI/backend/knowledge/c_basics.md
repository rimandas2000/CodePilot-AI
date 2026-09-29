# C Programming Basics

## Program structure

```c
#include <stdio.h>

int main() {
    printf("Hello World");
    return 0;
}
```

## Variables

```c
int age = 20;
float price = 10.5f;
char grade = 'A';
```

## Conditions

```c
if (age >= 18) {
    printf("Adult");
} else {
    printf("Minor");
}
```

## For loop

```c
for (int i = 0; i < 5; i++) {
    printf("%d\n", i);
}
```

## Arrays
C arrays use zero-based indexing.

```c
int numbers[3] = {10, 20, 30};
printf("%d", numbers[0]);
```

Accessing beyond the valid array boundary causes undefined behavior.

## Functions

```c
int add(int a, int b) {
    return a + b;
}
```

## Pointers
A pointer stores the address of another object.

```c
int x = 10;
int *p = &x;
printf("%d", *p);
```

Always initialize pointers before dereferencing them and avoid dereferencing invalid addresses.
